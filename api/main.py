"""
FastAPI 后端服务
提供 RESTful API 供前端调用
"""

import os
import sys
import asyncio
import contextlib
import copy
import inspect
import time
import uuid
from typing import List, Dict, Any, Optional
from pathlib import Path

# 添加 src 到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import Depends, FastAPI, File, UploadFile, Form, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.pipeline import DataPipeline
from src.ingestion import compute_content_hash, create_processing_manifest, file_key_for
from src.tasks import SQLiteTaskStore, TERMINAL_TASK_STATUSES
from src.llm import LLMConfigError, LLMProviderError, call_chat_model
from src.io.loaders import (
    LoaderOptions,
    SUPPORTED_EXTENSIONS,
    get_loader_diagnostics,
    load_documents_from_bytes,
)

# ========== Pydantic 模型 ==========

class ProcessRequest(BaseModel):
    """处理请求"""
    texts: Optional[List[str]] = None
    source_metadata: Optional[List[Dict[str, Any]]] = None
    background: bool = False

class ProcessResponse(BaseModel):
    """处理响应"""
    success: bool
    stats: Dict[str, Any]
    message: str
    task_id: str
    status: str = "completed"

class SearchRequest(BaseModel):
    """搜索请求"""
    query: str = Field(..., min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=50)
    threshold: Optional[float] = None
    filters: Optional[Dict[str, Any]] = None

class SearchResult(BaseModel):
    """搜索结果"""
    id: str
    text: str
    score: float
    metadata: Dict[str, Any]
    child_text: Optional[str] = None
    parent_context: Optional[str] = None
    context_text: Optional[str] = None
    parent_id: Optional[str] = None
    child_id: Optional[str] = None
    parent_type: Optional[str] = None
    parent_heading_path: Optional[str] = None
    parent_section_title: Optional[str] = None
    vector_score: Optional[float] = None
    rerank_score: Optional[float] = None

class SearchResponse(BaseModel):
    """搜索响应"""
    query: str
    results: List[SearchResult]
    total: int

class RagAskRequest(BaseModel):
    """RAG answer request."""
    question: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)
    threshold: Optional[float] = None
    filters: Optional[Dict[str, Any]] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = Field(default=None, ge=0, le=2)
    max_tokens: Optional[int] = Field(default=None, ge=1, le=8000)
    system_prompt: Optional[str] = None

class RagAskResponse(BaseModel):
    """RAG answer response."""
    question: str
    answer: str
    provider: str
    model: str
    prompt: str
    sources: List[SearchResult]
    total_sources: int
    usage: Dict[str, Any] = Field(default_factory=dict)
    latency_ms: int

class PreviewRequest(BaseModel):
    """预览请求"""
    texts: Optional[List[str]] = None
    source_metadata: Optional[List[Dict[str, Any]]] = None
    max_chunks: int = Field(default=20, ge=1, le=200)
    max_chars: int = Field(default=500, ge=50, le=5000)

class ChunkPreview(BaseModel):
    """分块预览"""
    text: str
    metadata: Dict[str, Any]

class PreviewResponse(BaseModel):
    """预览响应"""
    stats: Dict[str, Any]
    chunks: List[ChunkPreview]
    total_chunks: int
    quality_reports: List[Dict[str, Any]] = Field(default_factory=list)

class DBInfoResponse(BaseModel):
    """数据库信息"""
    db_type: str
    collection_name: str
    dimension: int
    count: int
    status: str

class ConfigResponse(BaseModel):
    """配置响应"""
    config: Dict[str, Any]

class DiagnosticsResponse(BaseModel):
    """运行环境诊断响应"""
    diagnostics: Dict[str, Any]

class TaskStatusResponse(BaseModel):
    """后台任务状态"""
    task_id: str
    action: str
    status: str
    created_at: float
    updated_at: float
    stats: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    progress: Dict[str, Any] = Field(default_factory=dict)
    message: str = ""
    attempts: int = 0
    max_attempts: int = 1
    available_at: Optional[float] = None
    locked_by: Optional[str] = None
    locked_at: Optional[float] = None

# ========== FastAPI 应用 ==========

app = FastAPI(
    title="数据清洗 + 向量数据库 API",
    description="提供数据清洗、向量存储和语义搜索的 RESTful API",
    version="1.0.0"
)

# CORS 配置（允许前端跨域访问）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/app", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")

# 全局流水线实例
pipeline: Optional[DataPipeline] = None
pipeline_lock = asyncio.Lock()
tasks: Dict[str, Dict[str, Any]] = {}
task_store: Optional[SQLiteTaskStore] = None
task_worker: Optional[asyncio.Task] = None
TASK_WORKER_ID = f"api-{os.getpid()}-{uuid.uuid4()}"
TASK_WORKER_ENABLED = True
TASK_MAX_ATTEMPTS = 2
TASK_RETRY_DELAY_SECONDS = 5
TASK_LEASE_TIMEOUT_SECONDS = 3600
TASK_POLL_INTERVAL_SECONDS = 1.0
MAX_TASK_HISTORY = 100


def require_api_key(
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    authorization: Optional[str] = Header(default=None)
):
    """当设置 API_KEY 环境变量时，要求请求携带 API Key。"""
    expected = os.environ.get("API_KEY")
    if not expected:
        return True

    token = x_api_key if isinstance(x_api_key, str) else None
    authorization = authorization if isinstance(authorization, str) else None
    if not token and authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer":
            token = value

    if token != expected:
        raise HTTPException(401, "缺少或无效的 API Key")

    return True


async def run_with_pipeline_lock(func, *args, **kwargs):
    """串行执行会读写 pipeline 状态的同步操作。"""
    async with pipeline_lock:
        return await asyncio.to_thread(func, *args, **kwargs)


def remember_task(task: Dict[str, Any]):
    """保存任务并限制历史数量。"""
    tasks[task["task_id"]] = task
    persist_task(task)
    if len(tasks) <= MAX_TASK_HISTORY:
        return

    removable = sorted(tasks.values(), key=lambda item: item["created_at"])
    for item in removable[:len(tasks) - MAX_TASK_HISTORY]:
        if item["status"] in TERMINAL_TASK_STATUSES:
            tasks.pop(item["task_id"], None)
    if task_store:
        task_store.prune(MAX_TASK_HISTORY)


def persist_task(task: Dict[str, Any]):
    if task_store:
        task_store.save_task(task)


def set_task_fields(task: Dict[str, Any], **updates: Any):
    task.update(updates)
    task["updated_at"] = updates.get("updated_at", time.time())
    persist_task(task)


def format_search_result(raw: Dict[str, Any]) -> SearchResult:
    """Expose parent-child retrieval fields while keeping the old text/metadata shape."""
    metadata = raw.get("metadata") or {}
    child_text = raw.get("text", "") or metadata.get("text", "")
    parent_context = metadata.get("parent_context")
    context_text = parent_context or child_text
    score = raw.get("rerank_score", raw.get("distance", raw.get("score", 0)))
    if "rerank_score" not in raw and "distance" in raw:
        score = max(0.0, 1 - score)

    return SearchResult(
        id=raw.get("id", "unknown"),
        text=child_text[:500],
        child_text=child_text,
        parent_context=parent_context,
        context_text=context_text,
        parent_id=metadata.get("parent_id"),
        child_id=metadata.get("child_id") or metadata.get("chunk_id"),
        parent_type=metadata.get("parent_type"),
        parent_heading_path=metadata.get("parent_heading_path") or metadata.get("heading_path"),
        parent_section_title=metadata.get("parent_section_title") or metadata.get("section_title"),
        score=round(score, 4),
        metadata=metadata,
        vector_score=raw.get("vector_score"),
        rerank_score=raw.get("rerank_score"),
    )


def source_label(result: SearchResult) -> str:
    metadata = result.metadata or {}
    parts = [
        metadata.get("filename") or metadata.get("file_key") or result.id,
        f"page={metadata.get('page_number')}" if metadata.get("page_number") else "",
        metadata.get("parent_heading_path") or metadata.get("heading_path") or "",
    ]
    return " / ".join(str(part) for part in parts if part)


def build_rag_messages(
    question: str,
    sources: List[SearchResult],
    system_prompt: Optional[str] = None,
    max_context_chars: int = 6000,
) -> tuple[List[Dict[str, str]], str]:
    """Build a citation-oriented RAG prompt from retrieved sources."""
    system = system_prompt or (
        "你是一个严谨的数据问答助手。只能根据提供的资料回答问题。"
        "如果资料不足，直接说明“当前资料不足以回答”。"
        "回答必须给出引用编号，例如 [1]、[2]。不要编造文件中没有的信息。"
        "如果不同资料之间存在冲突，请指出冲突并分别引用来源。"
    )
    remaining = max(500, int(max_context_chars))
    context_blocks: List[str] = []

    for index, result in enumerate(sources, start=1):
        text = result.context_text or result.parent_context or result.child_text or result.text
        text = (text or "").strip()
        if not text or remaining <= 0:
            continue
        label = source_label(result)
        block = f"[{index}] 来源: {label}\n{text}"
        if len(block) > remaining:
            block = block[:remaining].rstrip() + "..."
        context_blocks.append(block)
        remaining -= len(block)

    context = "\n\n".join(context_blocks)
    prompt = (
        "请根据以下资料回答问题。\n\n"
        f"资料:\n{context}\n\n"
        f"问题: {question}\n\n"
        "要求:\n"
        "1. 只使用资料中的信息。\n"
        "2. 每个关键结论后标注引用编号，例如 [1]。\n"
        "3. 如果资料不足，回答“当前资料不足以回答”。\n"
        "4. 回答先给结论，再给依据。"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ], prompt


def init_task_store():
    global task_store, tasks, MAX_TASK_HISTORY
    global TASK_WORKER_ENABLED, TASK_MAX_ATTEMPTS, TASK_RETRY_DELAY_SECONDS
    global TASK_LEASE_TIMEOUT_SECONDS, TASK_POLL_INTERVAL_SECONDS
    if not pipeline:
        return

    task_config = pipeline.config.get("tasks", {})
    MAX_TASK_HISTORY = int(task_config.get("max_history", MAX_TASK_HISTORY))
    TASK_WORKER_ENABLED = bool(task_config.get("worker_enabled", True))
    TASK_MAX_ATTEMPTS = int(task_config.get("max_attempts", TASK_MAX_ATTEMPTS))
    TASK_RETRY_DELAY_SECONDS = int(task_config.get("retry_delay_seconds", TASK_RETRY_DELAY_SECONDS))
    TASK_LEASE_TIMEOUT_SECONDS = int(task_config.get("lease_timeout_seconds", TASK_LEASE_TIMEOUT_SECONDS))
    TASK_POLL_INTERVAL_SECONDS = float(task_config.get("poll_interval_seconds", TASK_POLL_INTERVAL_SECONDS))
    if not task_config.get("enabled", True):
        task_store = None
        return

    store_path = task_config.get("store_path", "data/tasks.sqlite3")
    task_store = SQLiteTaskStore(store_path)
    task_store.requeue_incomplete()
    task_store.prune(MAX_TASK_HISTORY)
    tasks = {
        task["task_id"]: task
        for task in task_store.list_tasks(MAX_TASK_HISTORY)
    }
    ensure_task_worker_running()


def find_task(task_id: str) -> Optional[Dict[str, Any]]:
    task = tasks.get(task_id)
    if task:
        return task
    if task_store:
        task = task_store.get_task(task_id)
        if task:
            tasks[task_id] = task
            return task
    return None


def list_known_tasks() -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    if task_store:
        for task in task_store.list_tasks(MAX_TASK_HISTORY):
            merged[task["task_id"]] = task
    merged.update(tasks)
    return sorted(merged.values(), key=lambda item: item["created_at"], reverse=True)


def ensure_task_worker_running():
    global task_worker
    if not task_store or not TASK_WORKER_ENABLED:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if task_worker is None or task_worker.done():
        task_worker = loop.create_task(task_worker_loop())


async def task_worker_loop():
    while task_store and TASK_WORKER_ENABLED:
        task = await asyncio.to_thread(
            task_store.claim_next,
            TASK_WORKER_ID,
            TASK_LEASE_TIMEOUT_SECONDS,
        )
        if not task:
            await asyncio.sleep(TASK_POLL_INTERVAL_SECONDS)
            continue

        tasks[task["task_id"]] = task
        await run_queued_task(task)


async def run_queued_task(task: Dict[str, Any]):
    payload = task.get("payload")
    if not payload:
        set_task_fields(
            task,
            status="failed",
            error="Queued task payload is missing",
            message="任务失败",
            progress={
                "stage": "failed",
                "percent": 0,
                "message": "Queued task payload is missing",
            },
            payload=None,
            locked_by=None,
            locked_at=None,
        )
        return

    def update_progress(progress: Dict[str, Any]):
        updates = {"progress": progress}
        if progress.get("message"):
            updates["message"] = progress["message"]
        set_task_fields(task, **updates)

    try:
        action = task.get("action")
        if action == "process_texts":
            if not pipeline:
                raise RuntimeError("pipeline is not initialized")
            stats = await run_with_pipeline_lock(
                pipeline.process_texts,
                payload.get("texts", []),
                source_metadata=payload.get("source_metadata"),
                progress_callback=update_progress,
            )
        elif action in {"process_file", "process_files"}:
            stats = await run_with_pipeline_lock(
                process_documents_incremental,
                payload.get("texts", []),
                payload.get("metadatas", []),
                payload.get("manifest_updates", []),
                payload.get("skipped_files", []),
                progress_callback=update_progress,
            )
        else:
            raise ValueError(f"Unsupported queued task action: {action}")

        set_task_fields(
            task,
            status="succeeded",
            stats=stats,
            payload=None,
            locked_by=None,
            locked_at=None,
            progress={
                "stage": "completed",
                "percent": 100,
                "message": "Task completed",
            },
            message="任务完成",
        )
    except Exception as exc:
        attempts = int(task.get("attempts", 0))
        max_attempts = int(task.get("max_attempts", TASK_MAX_ATTEMPTS))
        if attempts < max_attempts:
            set_task_fields(
                task,
                status="pending",
                error=str(exc),
                available_at=time.time() + TASK_RETRY_DELAY_SECONDS,
                locked_by=None,
                locked_at=None,
                progress={
                    "stage": "retry_scheduled",
                    "percent": task.get("progress", {}).get("percent", 0),
                    "message": str(exc),
                },
                message="任务将重试",
            )
            return

        set_task_fields(
            task,
            status="failed",
            error=str(exc),
            payload=None,
            locked_by=None,
            locked_at=None,
            progress={
                "stage": "failed",
                "percent": task.get("progress", {}).get("percent", 0),
                "message": str(exc),
            },
            message="任务失败",
        )


async def run_background_task(task_id: str, func, *args, **kwargs):
    """执行后台任务并记录状态。"""
    task = tasks[task_id]
    set_task_fields(
        task,
        status="running",
        message="任务运行中",
        progress={
            "stage": "running",
            "percent": 1,
            "message": "Task started",
        },
    )

    def update_progress(progress: Dict[str, Any]):
        updates = {"progress": progress}
        if progress.get("message"):
            updates["message"] = progress["message"]
        set_task_fields(task, **updates)

    try:
        if "progress_callback" in inspect.signature(func).parameters:
            kwargs["progress_callback"] = update_progress
        stats = await run_with_pipeline_lock(func, *args, **kwargs)
        set_task_fields(
            task,
            status="succeeded",
            stats=stats,
            progress={
                "stage": "completed",
                "percent": 100,
                "message": "Task completed",
            },
            message="任务完成",
        )
    except Exception as exc:
        set_task_fields(
            task,
            status="failed",
            error=str(exc),
            progress={
                "stage": "failed",
                "percent": task.get("progress", {}).get("percent", 0),
                "message": str(exc),
            },
            message="任务失败",
        )
    finally:
        set_task_fields(task)


def submit_background_task(action: str, func, *args, payload: Optional[Dict[str, Any]] = None, **kwargs) -> str:
    """提交后台任务。"""
    task_id = str(uuid.uuid4())
    now = time.time()
    max_attempts = int(kwargs.pop("max_attempts", TASK_MAX_ATTEMPTS))
    remember_task({
        "task_id": task_id,
        "action": action,
        "status": "pending",
        "created_at": now,
        "updated_at": now,
        "stats": None,
        "error": None,
        "progress": {
            "stage": "pending",
            "percent": 0,
            "message": "Task submitted",
        },
        "message": "任务已提交",
        "payload": payload,
        "attempts": 0,
        "max_attempts": max_attempts,
        "available_at": now,
        "locked_by": None,
        "locked_at": None,
    })
    if task_store and payload is not None and TASK_WORKER_ENABLED:
        ensure_task_worker_running()
    else:
        asyncio.create_task(run_background_task(task_id, func, *args, **kwargs))
    return task_id


def build_loader_options(
    text_fields: Optional[str],
    max_file_size_mb: int,
    max_records: Optional[int],
    excel_header_row: Optional[int] = None,
    excel_header_rows: int = 1,
    excel_row_documents: bool = True,
    docx_split_by_heading: bool = True,
    pdf_infer_sections: bool = True,
    ocr_enabled: bool = False,
    ocr_backend: str = "tesseract",
    ocr_language: str = "eng",
    ocr_dpi: int = 200,
    ocr_max_pages: Optional[int] = None
) -> LoaderOptions:
    """从 API 表单参数构建文件加载配置。"""
    fields = None
    if text_fields:
        fields = [field.strip() for field in text_fields.split(",") if field.strip()]

    return LoaderOptions(
        text_fields=fields,
        max_file_size_mb=max_file_size_mb,
        max_records=max_records,
        excel_header_row=excel_header_row,
        excel_header_rows=excel_header_rows,
        excel_row_documents=excel_row_documents,
        docx_split_by_heading=docx_split_by_heading,
        pdf_infer_sections=pdf_infer_sections,
        ocr_enabled=ocr_enabled,
        ocr_backend=ocr_backend,
        ocr_language=ocr_language,
        ocr_dpi=ocr_dpi,
        ocr_max_pages=ocr_max_pages,
    )


def deep_update(base: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    """递归合并配置，避免局部更新覆盖整个配置段。"""
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_update(base[key], value)
        else:
            base[key] = value
    return base


def build_diagnostics() -> Dict[str, Any]:
    diagnostics = get_loader_diagnostics()
    diagnostics["pipeline"] = {
        "ready": pipeline is not None,
    }

    if pipeline:
        diagnostics["pipeline"].update({
            "vector_db": pipeline.config.get("vector_db", {}).get("type"),
            "embedding": {
                "provider": pipeline.config.get("embedding", {}).get("provider"),
                "model_name": pipeline.config.get("embedding", {}).get("model_name"),
                "dimension": getattr(pipeline.embedding_model, "dimension", None),
            },
            "reranker": pipeline.config.get("reranker", {}),
            "ingestion": pipeline.config.get("ingestion", {}),
            "tasks": pipeline.config.get("tasks", {}),
            "metadata_db": {
                "enabled": pipeline.config.get("metadata_db", {}).get("enabled", False),
                "type": pipeline.config.get("metadata_db", {}).get("type", "disabled"),
                "store": getattr(pipeline, "metadata_store", None).health()
                if getattr(pipeline, "metadata_store", None)
                else {"enabled": False, "type": "disabled", "status": "missing"},
            },
        })

    return diagnostics


def get_manifest_path() -> str:
    if pipeline:
        ingestion_config = pipeline.config.get("ingestion", {})
        return ingestion_config.get("manifest_path", "data/manifest.sqlite3")
    return "data/manifest.sqlite3"


def get_manifest_backend() -> str:
    if pipeline:
        ingestion_config = pipeline.config.get("ingestion", {})
        return ingestion_config.get("manifest_backend", "auto")
    return "auto"


def get_processing_manifest():
    return create_processing_manifest(get_manifest_path(), backend=get_manifest_backend())


def list_manifest_files() -> Dict[str, Any]:
    manifest = get_processing_manifest()
    manifest_data = manifest.to_dict()
    files = list((manifest_data.get("files") or {}).values())
    files.sort(key=lambda item: item.get("processed_at") or 0, reverse=True)
    return {
        "backend": manifest_data.get("backend", get_manifest_backend()),
        "path": get_manifest_path(),
        "total": len(files),
        "files": files,
    }


def build_manifest_update(
    *,
    filename: str,
    file_key: str,
    content_hash: str,
    size_bytes: int,
    document_count: int,
    old_record: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "filename": filename,
        "file_key": file_key,
        "file_type": Path(filename).suffix.lower(),
        "content_hash": content_hash,
        "size_bytes": size_bytes,
        "document_count": document_count,
        "old_chunk_ids": list((old_record or {}).get("chunk_ids") or []),
        "source_file": old_record.get("source_file") if old_record else None,
    }


def build_skipped_file(
    filename: str,
    file_key: str,
    content_hash: str,
    reason: str,
    old_record: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "file": file_key,
        "file_key": file_key,
        "filename": filename,
        "content_hash": content_hash,
        "reason": reason,
        "status": "skipped",
        "previous_processed_at": (old_record or {}).get("processed_at"),
        "previous_chunk_count": (old_record or {}).get("chunk_count", 0),
    }


def build_skipped_stats(skipped_files: List[Any]) -> Dict[str, Any]:
    summary = {
        "input_count": 0,
        "cleaned_count": 0,
        "filtered_count": 0,
        "deduped_count": 0,
        "chunked_count": 0,
        "stored_count": 0,
    }
    return {
        **summary,
        "quality_summary": {
            "scored_count": 0,
            "rejected_count": 0,
            "average_score": 0,
            "reason_counts": {},
        },
        "processing_report": {
            "summary": summary,
            "files": [],
            "skipped_files": skipped_files,
            "incremental": {
                "processed": [],
                "skipped": skipped_files,
                "deleted_vector_count": 0,
            },
        },
    }


def find_file_report(stats: Dict[str, Any], update: Dict[str, Any]) -> Dict[str, Any]:
    reports = stats.get("processing_report", {}).get("files", [])
    for report in reports:
        if report.get("file_key") == update["file_key"] or report.get("file") == update["file_key"]:
            return report
        if report.get("filename") == update["filename"] and report.get("file_hash") == update["content_hash"]:
            return report
    return {}


def process_documents_incremental(
    texts: List[str],
    metadatas: List[Dict[str, Any]],
    manifest_updates: List[Dict[str, Any]],
    skipped_files: Optional[List[Any]] = None,
    progress_callback=None,
) -> Dict[str, Any]:
    if not pipeline:
        raise RuntimeError("pipeline is not initialized")

    skipped_files = list(skipped_files or [])
    deleted_vector_count = 0
    for update in manifest_updates:
        old_chunk_ids = update.get("old_chunk_ids") or []
        if old_chunk_ids and pipeline.vector_db:
            pipeline.vector_db.delete(old_chunk_ids)
            deleted_vector_count += len(old_chunk_ids)

    stats = pipeline.process_texts(
        texts,
        source_metadata=metadatas,
        progress_callback=progress_callback,
    )

    manifest = get_processing_manifest()
    processed_records = []
    for update in manifest_updates:
        report = find_file_report(stats, update)
        record = manifest.mark_processed(
            file_key=update["file_key"],
            content_hash=update["content_hash"],
            filename=update["filename"],
            file_type=update.get("file_type"),
            size_bytes=update.get("size_bytes", 0),
            document_count=update.get("document_count", 0),
            chunk_count=report.get("chunks", 0),
            chunk_ids=report.get("chunk_ids", []),
            source_file=update.get("source_file"),
            stats={
                "input_documents": report.get("input_documents", 0),
                "rejected_documents": report.get("rejected_documents", 0),
                "rejection_reasons": report.get("rejection_reasons", {}),
            },
        )
        processed_records.append(record)

    manifest.save()
    processing_report = stats.setdefault("processing_report", {})
    if skipped_files:
        processing_report["skipped_files"] = skipped_files
    processing_report["incremental"] = {
        "processed": processed_records,
        "skipped": skipped_files,
        "deleted_vector_count": deleted_vector_count,
    }
    return stats

# ========== 生命周期 ==========

@app.on_event("startup")
async def startup():
    """启动时初始化流水线"""
    global pipeline
    try:
        config_path = os.environ.get("CONFIG_PATH", "config.yaml")
        pipeline = DataPipeline(config_path=config_path)
        pipeline.init_vector_db()
        init_task_store()
        print("流水线初始化成功")
    except Exception as e:
        print(f"流水线初始化失败: {e}")

@app.on_event("shutdown")
async def shutdown():
    """关闭时释放资源"""
    global pipeline, task_worker
    if task_worker and not task_worker.done():
        task_worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task_worker
        task_worker = None
    if pipeline:
        pipeline.close()
        print("资源已释放")

# ========== API 路由 ==========

@app.get("/", tags=["健康检查"])
async def root():
    """根路径 - 服务状态"""
    return {
        "service": "数据清洗 + 向量数据库 API",
        "version": "1.0.0",
        "status": "running",
        "pipeline_ready": pipeline is not None
    }

@app.get("/health", tags=["健康检查"])
async def health():
    """健康检查"""
    return {"status": "healthy", "pipeline_ready": pipeline is not None}

@app.get("/api/diagnostics", response_model=DiagnosticsResponse, tags=["健康检查"])
async def diagnostics(_auth: bool = Depends(require_api_key)):
    """返回当前环境对复杂文件、OCR、向量配置的支持状态。"""
    return DiagnosticsResponse(diagnostics=build_diagnostics())

# ----- 数据处理 -----

@app.post("/api/process", response_model=ProcessResponse, tags=["数据处理"])
async def process_texts(request: ProcessRequest, _auth: bool = Depends(require_api_key)):
    """处理文本并入库"""
    if not pipeline:
        raise HTTPException(503, "流水线未初始化")

    if not request.texts:
        raise HTTPException(400, "texts 不能为空")

    try:
        if request.background:
            task_id = submit_background_task(
                "process_texts",
                pipeline.process_texts,
                request.texts,
                source_metadata=request.source_metadata,
                payload={
                    "texts": request.texts,
                    "source_metadata": request.source_metadata,
                },
            )
            return ProcessResponse(
                success=True,
                stats={},
                message="任务已提交",
                task_id=task_id,
                status="pending"
            )

        task_id = str(uuid.uuid4())
        stats = await run_with_pipeline_lock(
            pipeline.process_texts,
            request.texts,
            source_metadata=request.source_metadata
        )
        return ProcessResponse(
            success=True,
            stats=stats,
            message="处理成功",
            task_id=task_id
        )
    except Exception as e:
        raise HTTPException(500, f"处理失败: {str(e)}")

@app.post("/api/process/file", response_model=ProcessResponse, tags=["数据处理"])
async def process_file(
    file: UploadFile = File(...),
    chunk_size: Optional[int] = Form(512),
    chunk_overlap: Optional[int] = Form(128),
    background: bool = Form(False),
    text_fields: Optional[str] = Form(None),
    max_file_size_mb: int = Form(100),
    max_records: Optional[int] = Form(None),
    excel_header_row: Optional[int] = Form(None),
    excel_header_rows: int = Form(1),
    excel_row_documents: bool = Form(True),
    docx_split_by_heading: bool = Form(True),
    pdf_infer_sections: bool = Form(True),
    ocr_enabled: bool = Form(False),
    ocr_backend: str = Form("tesseract"),
    ocr_language: str = Form("eng"),
    ocr_dpi: int = Form(200),
    ocr_max_pages: Optional[int] = Form(None),
    incremental: bool = Form(True),
    force_reprocess: bool = Form(False),
    _auth: bool = Depends(require_api_key)
):
    """上传文件并处理"""
    if not pipeline:
        raise HTTPException(503, "流水线未初始化")

    filename = file.filename or "upload.txt"
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(400, f"不支持的文件类型: {ext}")

    try:
        content = await file.read()
        content_hash = compute_content_hash(content)
        file_key = file_key_for(filename)
        manifest = get_processing_manifest()
        old_record = manifest.get(file_key)
        if incremental and not force_reprocess and manifest.is_unchanged(file_key, content_hash):
            skipped_file = build_skipped_file(
                filename,
                file_key,
                content_hash,
                "unchanged",
                old_record,
            )
            return ProcessResponse(
                success=True,
                stats=build_skipped_stats([skipped_file]),
                message=f"文件 {filename} 未变化，已跳过",
                task_id=str(uuid.uuid4()),
                status="skipped",
            )

        loader_options = build_loader_options(
            text_fields,
            max_file_size_mb,
            max_records,
            excel_header_row=excel_header_row,
            excel_header_rows=excel_header_rows,
            excel_row_documents=excel_row_documents,
            docx_split_by_heading=docx_split_by_heading,
            pdf_infer_sections=pdf_infer_sections,
            ocr_enabled=ocr_enabled,
            ocr_backend=ocr_backend,
            ocr_language=ocr_language,
            ocr_dpi=ocr_dpi,
            ocr_max_pages=ocr_max_pages,
        )
        base_metadata = {
            "file_key": file_key,
            "file_hash": content_hash,
            "content_hash": content_hash,
            "file_size_bytes": len(content),
        }
        texts, metadatas = load_documents_from_bytes(
            filename,
            content,
            base_metadata=base_metadata,
            options=loader_options,
        )
        if not texts:
            raise HTTPException(400, "文件没有可处理的文本内容")

        manifest_updates = [
            build_manifest_update(
                filename=filename,
                file_key=file_key,
                content_hash=content_hash,
                size_bytes=len(content),
                document_count=len(texts),
                old_record=old_record if incremental else None,
            )
        ]

        if background:
            task_id = submit_background_task(
                "process_file",
                process_documents_incremental,
                texts,
                metadatas,
                manifest_updates,
                payload={
                    "texts": texts,
                    "metadatas": metadatas,
                    "manifest_updates": manifest_updates,
                    "skipped_files": [],
                },
            )
            return ProcessResponse(
                success=True,
                stats={},
                message=f"文件 {filename} 已提交后台处理",
                task_id=task_id,
                status="pending"
            )

        task_id = str(uuid.uuid4())
        stats = await run_with_pipeline_lock(
            process_documents_incremental,
            texts,
            metadatas,
            manifest_updates,
        )

        return ProcessResponse(
            success=True,
            stats=stats,
            message=f"文件 {filename} 处理成功",
            task_id=task_id
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(400, str(e))
    except ImportError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"文件处理失败: {str(e)}")

@app.post("/api/process/files", response_model=ProcessResponse, tags=["数据处理"])
async def process_files(
    files: List[UploadFile] = File(...),
    background: bool = Form(False),
    text_fields: Optional[str] = Form(None),
    max_file_size_mb: int = Form(100),
    max_records: Optional[int] = Form(None),
    excel_header_row: Optional[int] = Form(None),
    excel_header_rows: int = Form(1),
    excel_row_documents: bool = Form(True),
    docx_split_by_heading: bool = Form(True),
    pdf_infer_sections: bool = Form(True),
    ocr_enabled: bool = Form(False),
    ocr_backend: str = Form("tesseract"),
    ocr_language: str = Form("eng"),
    ocr_dpi: int = Form(200),
    ocr_max_pages: Optional[int] = Form(None),
    incremental: bool = Form(True),
    force_reprocess: bool = Form(False),
    _auth: bool = Depends(require_api_key)
):
    """批量上传文件并处理"""
    if not pipeline:
        raise HTTPException(503, "流水线未初始化")

    texts = []
    metadatas = []
    loader_options = build_loader_options(
        text_fields,
        max_file_size_mb,
        max_records,
        excel_header_row=excel_header_row,
        excel_header_rows=excel_header_rows,
        excel_row_documents=excel_row_documents,
        docx_split_by_heading=docx_split_by_heading,
        pdf_infer_sections=pdf_infer_sections,
        ocr_enabled=ocr_enabled,
        ocr_backend=ocr_backend,
        ocr_language=ocr_language,
        ocr_dpi=ocr_dpi,
        ocr_max_pages=ocr_max_pages,
    )
    skipped_files = []
    manifest_updates = []
    manifest = get_processing_manifest()

    for file in files:
        filename = file.filename or "upload.txt"
        ext = Path(filename).suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            skipped_files.append(f"{filename}: 不支持的文件类型 {ext}")
            continue

        content = await file.read()
        content_hash = compute_content_hash(content)
        file_key = file_key_for(filename)
        old_record = manifest.get(file_key)
        if incremental and not force_reprocess and manifest.is_unchanged(file_key, content_hash):
            skipped_files.append(
                build_skipped_file(
                    filename,
                    file_key,
                    content_hash,
                    "unchanged",
                    old_record,
                )
            )
            continue

        try:
            base_metadata = {
                "file_key": file_key,
                "file_hash": content_hash,
                "content_hash": content_hash,
                "file_size_bytes": len(content),
            }
            file_texts, file_metadatas = load_documents_from_bytes(
                filename,
                content,
                base_metadata=base_metadata,
                options=loader_options,
            )
            texts.extend(file_texts)
            metadatas.extend(file_metadatas)
            manifest_updates.append(
                build_manifest_update(
                    filename=filename,
                    file_key=file_key,
                    content_hash=content_hash,
                    size_bytes=len(content),
                    document_count=len(file_texts),
                    old_record=old_record if incremental else None,
                )
            )
        except (ValueError, ImportError) as e:
            skipped_files.append(f"{filename}: {e}")
        except Exception as e:
            skipped_files.append(f"{filename}: 解析失败 {e}")
            continue

    if not texts and skipped_files and all(
        isinstance(item, dict) and item.get("reason") == "unchanged"
        for item in skipped_files
    ):
        return ProcessResponse(
            success=True,
            stats=build_skipped_stats(skipped_files),
            message="所有文件未变化，已跳过",
            task_id=str(uuid.uuid4()),
            status="skipped",
        )

    if not texts:
        detail = "没有有效的文本文件"
        if skipped_files:
            detail = f"{detail}: {'; '.join(str(item) for item in skipped_files)}"
        raise HTTPException(400, detail)

    try:
        if background:
            task_id = submit_background_task(
                "process_files",
                process_documents_incremental,
                texts,
                metadatas,
                manifest_updates,
                skipped_files,
                payload={
                    "texts": texts,
                    "metadatas": metadatas,
                    "manifest_updates": manifest_updates,
                    "skipped_files": skipped_files,
                },
            )
            return ProcessResponse(
                success=True,
                stats={},
                message=f"已提交 {len(texts)} 个文件片段到后台处理",
                task_id=task_id,
                status="pending"
            )

        task_id = str(uuid.uuid4())
        stats = await run_with_pipeline_lock(
            process_documents_incremental,
            texts,
            metadatas,
            manifest_updates,
            skipped_files,
        )
        if skipped_files:
            stats.setdefault("processing_report", {})["skipped_files"] = skipped_files
        return ProcessResponse(
            success=True,
            stats=stats,
            message=f"成功处理 {len(texts)} 个文件",
            task_id=task_id
        )
    except Exception as e:
        raise HTTPException(500, f"批量处理失败: {str(e)}")

@app.post("/api/preview", response_model=PreviewResponse, tags=["数据处理"])
async def preview_texts(request: PreviewRequest, _auth: bool = Depends(require_api_key)):
    """预览清洗、过滤、去重和分块结果，不写入向量数据库"""
    if not pipeline:
        raise HTTPException(503, "流水线未初始化")

    if not request.texts:
        raise HTTPException(400, "texts 不能为空")

    try:
        prepared = await run_with_pipeline_lock(
            pipeline.prepare_texts,
            request.texts,
            source_metadata=request.source_metadata,
            mutate_dedup=False,
            max_preview_chars=request.max_chars
        )
        chunks = [
            ChunkPreview(text=item.get('text', ''), metadata=item.get('metadata', {}))
            for item in prepared['chunks'][:request.max_chunks]
        ]
        return PreviewResponse(
            stats=prepared['stats'],
            chunks=chunks,
            total_chunks=len(prepared['chunks']),
            quality_reports=prepared.get('quality_reports', [])
        )
    except Exception as e:
        raise HTTPException(500, f"预览失败: {str(e)}")

# ----- 搜索 -----

@app.post("/api/search", response_model=SearchResponse, tags=["搜索"])
async def search(request: SearchRequest, _auth: bool = Depends(require_api_key)):
    """语义搜索"""
    if not pipeline:
        raise HTTPException(503, "流水线未初始化")

    try:
        results = await run_with_pipeline_lock(
            pipeline.search,
            request.query,
            top_k=request.top_k,
            filter_dict=request.filters
        )

        formatted = [format_search_result(result) for result in results]

        if request.threshold is not None:
            formatted = [r for r in formatted if r.score >= request.threshold]

        return SearchResponse(
            query=request.query,
            results=formatted,
            total=len(formatted)
        )
    except Exception as e:
        raise HTTPException(500, f"搜索失败: {str(e)}")

@app.get("/api/search", response_model=SearchResponse, tags=["搜索"])
async def search_get(
    query: str,
    top_k: int = 5,
    threshold: Optional[float] = None,
    _auth: bool = Depends(require_api_key)
):
    """GET 方式搜索"""
    return await search(SearchRequest(query=query, top_k=top_k, threshold=threshold))


@app.post("/api/rag/ask", response_model=RagAskResponse, tags=["RAG"])
async def rag_ask(request: RagAskRequest, _auth: bool = Depends(require_api_key)):
    """检索召回后调用配置的大模型生成带引用回答。"""
    if not pipeline:
        raise HTTPException(503, "流水线未初始化")

    try:
        results = await run_with_pipeline_lock(
            pipeline.search,
            request.question,
            top_k=request.top_k,
            filter_dict=request.filters
        )
        sources = [format_search_result(result) for result in results]
        if request.threshold is not None:
            sources = [source for source in sources if source.score >= request.threshold]

        if not sources:
            raise HTTPException(404, "没有召回到可用于 RAG 的上下文")

        llm_config = pipeline.config.get("llm") or {}
        max_context_chars = int(llm_config.get("max_context_chars", 6000))
        messages, prompt = build_rag_messages(
            request.question,
            sources,
            system_prompt=request.system_prompt or llm_config.get("system_prompt"),
            max_context_chars=max_context_chars,
        )
        started_at = time.time()
        llm_result = await asyncio.to_thread(
            call_chat_model,
            llm_config,
            messages,
            {
                "provider": request.provider,
                "model": request.model,
                "temperature": request.temperature,
                "max_tokens": request.max_tokens,
            },
        )

        return RagAskResponse(
            question=request.question,
            answer=llm_result["answer"],
            provider=llm_result["provider"],
            model=llm_result["model"],
            prompt=prompt,
            sources=sources,
            total_sources=len(sources),
            usage=llm_result.get("usage") or {},
            latency_ms=int((time.time() - started_at) * 1000),
        )
    except HTTPException:
        raise
    except LLMConfigError as e:
        raise HTTPException(503, str(e))
    except LLMProviderError as e:
        raise HTTPException(502, str(e))
    except Exception as e:
        raise HTTPException(500, f"RAG 问答失败: {str(e)}")


@app.get("/api/tasks/{task_id}", response_model=TaskStatusResponse, tags=["任务"])
async def get_task(task_id: str, _auth: bool = Depends(require_api_key)):
    """查询后台任务状态"""
    task = find_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    return TaskStatusResponse(**task)

@app.get("/api/tasks", response_model=List[TaskStatusResponse], tags=["任务"])
async def list_tasks(_auth: bool = Depends(require_api_key)):
    """列出后台任务状态"""
    return [
        TaskStatusResponse(**task)
        for task in list_known_tasks()
    ]

@app.get("/api/files", tags=["文件"])
async def list_files(_auth: bool = Depends(require_api_key)):
    """List files tracked by the incremental processing manifest."""
    if not pipeline:
        raise HTTPException(503, "流水线未初始化")

    try:
        return await run_with_pipeline_lock(list_manifest_files)
    except Exception as e:
        raise HTTPException(500, f"获取文件历史失败: {str(e)}")


@app.get("/api/files/{file_key:path}", tags=["文件"])
async def get_file_detail(file_key: str, _auth: bool = Depends(require_api_key)):
    """Get one manifest file record by file_key."""
    if not pipeline:
        raise HTTPException(503, "流水线未初始化")

    try:
        manifest = get_processing_manifest()
        record = await run_with_pipeline_lock(manifest.get, file_key)
    except Exception as e:
        raise HTTPException(500, f"获取文件详情失败: {str(e)}")
    if not record:
        raise HTTPException(404, "文件记录不存在")
    return record

# ----- 数据库管理 -----

@app.get("/api/metadata/status", tags=["数据库"])
async def metadata_status(_auth: bool = Depends(require_api_key)):
    """Return route-A metadata database status."""
    if not pipeline:
        raise HTTPException(503, "流水线未初始化")

    store = getattr(pipeline, "metadata_store", None)
    config = pipeline.config.get("metadata_db", {})
    return {
        "enabled": bool(config.get("enabled", False)),
        "type": config.get("type", "disabled"),
        "store": store.health() if store else {"enabled": False, "type": "disabled", "status": "missing"},
    }


@app.get("/api/metadata/runs", tags=["数据库"])
async def metadata_runs(limit: int = 20, _auth: bool = Depends(require_api_key)):
    """List recent processing runs from the metadata database."""
    if not pipeline:
        raise HTTPException(503, "流水线未初始化")

    store = getattr(pipeline, "metadata_store", None)
    if not store or not store.enabled:
        return {"enabled": False, "runs": []}

    safe_limit = max(1, min(int(limit), 100))
    try:
        runs = await run_with_pipeline_lock(store.get_recent_runs, safe_limit)
        return {"enabled": True, "runs": runs}
    except Exception as e:
        raise HTTPException(500, f"获取元数据处理批次失败: {str(e)}")


@app.get("/api/metadata/runs/{run_id}", tags=["数据库"])
async def metadata_run_detail(run_id: str, _auth: bool = Depends(require_api_key)):
    """Get one processing run with persisted chunk audit metadata."""
    if not pipeline:
        raise HTTPException(503, "流水线未初始化")

    store = getattr(pipeline, "metadata_store", None)
    if not store or not store.enabled:
        raise HTTPException(503, "metadata_db 未启用")

    try:
        run = await run_with_pipeline_lock(store.get_run, run_id)
    except Exception as e:
        raise HTTPException(500, f"获取元数据处理批次失败: {str(e)}")
    if not run:
        raise HTTPException(404, "处理批次不存在")
    return run


@app.get("/api/db/info", response_model=DBInfoResponse, tags=["数据库"])
async def db_info(_auth: bool = Depends(require_api_key)):
    """获取数据库信息"""
    if not pipeline:
        raise HTTPException(503, "流水线未初始化")

    try:
        info = await run_with_pipeline_lock(pipeline.get_stats)
        db_type = pipeline.config.get('vector_db', {}).get('type', 'chroma')

        return DBInfoResponse(
            db_type=db_type,
            collection_name=info.get('name', 'documents'),
            dimension=info.get('dimension', 1024),
            count=info.get('count', info.get('vectors_count', 0)),
            status=info.get('status', 'active')
        )
    except Exception as e:
        raise HTTPException(500, f"获取数据库信息失败: {str(e)}")

@app.delete("/api/db/clear", tags=["数据库"])
async def db_clear(_auth: bool = Depends(require_api_key)):
    """清空数据库"""
    if not pipeline:
        raise HTTPException(503, "流水线未初始化")

    if not pipeline.vector_db:
        raise HTTPException(503, "向量数据库未初始化")

    try:
        await run_with_pipeline_lock(pipeline.clear_vector_db, reset_dedup=True)

        return {"success": True, "message": "数据库和去重状态已清空"}
    except Exception as e:
        raise HTTPException(500, f"清空失败: {str(e)}")

# ----- 配置管理 -----

@app.get("/api/config", response_model=ConfigResponse, tags=["配置"])
async def get_config(_auth: bool = Depends(require_api_key)):
    """获取当前配置"""
    if not pipeline:
        raise HTTPException(503, "流水线未初始化")

    return ConfigResponse(config=pipeline.config)

@app.post("/api/config", tags=["配置"])
async def update_config(config: Dict[str, Any], _auth: bool = Depends(require_api_key)):
    """更新配置"""
    if not pipeline:
        raise HTTPException(503, "流水线未初始化")

    try:
        async with pipeline_lock:
            old_config = copy.deepcopy(pipeline.config)
            old_vector_db = pipeline.vector_db
            old_metadata_store = getattr(pipeline, "metadata_store", None)
            new_config = copy.deepcopy(pipeline.config)
            deep_update(new_config, config)

            pipeline.config = new_config

            try:
                await asyncio.to_thread(pipeline._init_components)
                if old_vector_db:
                    await asyncio.to_thread(old_vector_db.close)
                if old_metadata_store:
                    await asyncio.to_thread(old_metadata_store.close)
                await asyncio.to_thread(pipeline.init_vector_db)
            except Exception:
                new_metadata_store = getattr(pipeline, "metadata_store", None)
                if new_metadata_store and new_metadata_store is not old_metadata_store:
                    with contextlib.suppress(Exception):
                        await asyncio.to_thread(new_metadata_store.close)
                pipeline.config = old_config
                await asyncio.to_thread(pipeline._init_components)
                pipeline.vector_db = old_vector_db
                raise
        return {"success": True, "message": "配置已更新"}
    except Exception as e:
        raise HTTPException(500, f"配置更新失败: {str(e)}")

# ========== 启动入口 ==========

if __name__ == "__main__":
    import uvicorn
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0", help="绑定地址")
    parser.add_argument("--port", type=int, default=8000, help="端口")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    parser.add_argument("--reload", action="store_true", help="开发模式自动重载")

    args = parser.parse_args()

    os.environ["CONFIG_PATH"] = args.config

    uvicorn.run(
        "api.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info"
    )
