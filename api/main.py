"""
FastAPI 后端服务
提供 RESTful API 供前端调用
"""

import os
import sys
import uuid
from typing import List, Dict, Any, Optional
from pathlib import Path

# 添加 src 到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.pipeline import DataPipeline

# ========== Pydantic 模型 ==========

class ProcessRequest(BaseModel):
    """处理请求"""
    texts: Optional[List[str]] = None

class ProcessResponse(BaseModel):
    """处理响应"""
    success: bool
    stats: Dict[str, Any]
    message: str
    task_id: str

class SearchRequest(BaseModel):
    """搜索请求"""
    query: str = Field(..., min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=50)
    threshold: Optional[float] = Field(default=None, ge=0, le=1)

class SearchResult(BaseModel):
    """搜索结果"""
    id: str
    text: str
    score: float
    metadata: Dict[str, Any]

class SearchResponse(BaseModel):
    """搜索响应"""
    query: str
    results: List[SearchResult]
    total: int

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

# 全局流水线实例
pipeline: Optional[DataPipeline] = None

# ========== 生命周期 ==========

@app.on_event("startup")
async def startup():
    """启动时初始化流水线"""
    global pipeline
    try:
        config_path = os.environ.get("CONFIG_PATH", "config.yaml")
        pipeline = DataPipeline(config_path=config_path)
        pipeline.init_vector_db()
        print("✅ 流水线初始化成功")
    except Exception as e:
        print(f"⚠️ 流水线初始化失败: {e}")

@app.on_event("shutdown")
async def shutdown():
    """关闭时释放资源"""
    global pipeline
    if pipeline:
        pipeline.close()
        print("✅ 资源已释放")

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

# ----- 数据处理 -----

@app.post("/api/process", response_model=ProcessResponse, tags=["数据处理"])
async def process_texts(request: ProcessRequest):
    """处理文本并入库"""
    if not pipeline:
        raise HTTPException(503, "流水线未初始化")

    if not request.texts:
        raise HTTPException(400, "texts 不能为空")

    task_id = str(uuid.uuid4())

    try:
        stats = pipeline.process_texts(request.texts)
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
    chunk_overlap: Optional[int] = Form(128)
):
    """上传文件并处理"""
    if not pipeline:
        raise HTTPException(503, "流水线未初始化")

    allowed = {'.txt', '.md', '.json'}
    ext = Path(file.filename).suffix.lower()
    if ext not in allowed:
        raise HTTPException(400, f"不支持的文件类型: {ext}")

    task_id = str(uuid.uuid4())

    try:
        content = await file.read()
        text = content.decode('utf-8')

        stats = pipeline.process_texts([text], source_metadata=[{'filename': file.filename}])

        return ProcessResponse(
            success=True,
            stats=stats,
            message=f"文件 {file.filename} 处理成功",
            task_id=task_id
        )
    except Exception as e:
        raise HTTPException(500, f"文件处理失败: {str(e)}")

@app.post("/api/process/files", response_model=ProcessResponse, tags=["数据处理"])
async def process_files(
    files: List[UploadFile] = File(...)
):
    """批量上传文件并处理"""
    if not pipeline:
        raise HTTPException(503, "流水线未初始化")

    task_id = str(uuid.uuid4())
    texts = []
    metadatas = []

    for file in files:
        ext = Path(file.filename).suffix.lower()
        if ext not in {'.txt', '.md', '.json'}:
            continue

        content = await file.read()
        try:
            text = content.decode('utf-8')
            texts.append(text)
            metadatas.append({'filename': file.filename})
        except:
            continue

    if not texts:
        raise HTTPException(400, "没有有效的文本文件")

    try:
        stats = pipeline.process_texts(texts, source_metadata=metadatas)
        return ProcessResponse(
            success=True,
            stats=stats,
            message=f"成功处理 {len(texts)} 个文件",
            task_id=task_id
        )
    except Exception as e:
        raise HTTPException(500, f"批量处理失败: {str(e)}")

# ----- 搜索 -----

@app.post("/api/search", response_model=SearchResponse, tags=["搜索"])
async def search(request: SearchRequest):
    """语义搜索"""
    if not pipeline:
        raise HTTPException(503, "流水线未初始化")

    try:
        results = pipeline.search(request.query, top_k=request.top_k)

        formatted = []
        for r in results:
            score = r.get('distance', r.get('score', 0))
            if 'distance' in r:
                score = 1 - score

            formatted.append(SearchResult(
                id=r.get('id', 'unknown'),
                text=r.get('text', '')[:500],
                score=round(score, 4),
                metadata=r.get('metadata', {})
            ))

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
    threshold: Optional[float] = None
):
    """GET 方式搜索"""
    return await search(SearchRequest(query=query, top_k=top_k, threshold=threshold))

# ----- 数据库管理 -----

@app.get("/api/db/info", response_model=DBInfoResponse, tags=["数据库"])
async def db_info():
    """获取数据库信息"""
    if not pipeline:
        raise HTTPException(503, "流水线未初始化")

    try:
        info = pipeline.get_stats()
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
async def db_clear():
    """清空数据库"""
    if not pipeline:
        raise HTTPException(503, "流水线未初始化")

    try:
        if hasattr(pipeline.vector_db, 'collection'):
            all_docs = pipeline.vector_db.collection.get()
            if all_docs and all_docs.get('ids'):
                pipeline.vector_db.delete(all_docs['ids'])

        return {"success": True, "message": "数据库已清空"}
    except Exception as e:
        raise HTTPException(500, f"清空失败: {str(e)}")

# ----- 配置管理 -----

@app.get("/api/config", response_model=ConfigResponse, tags=["配置"])
async def get_config():
    """获取当前配置"""
    if not pipeline:
        raise HTTPException(503, "流水线未初始化")

    return ConfigResponse(config=pipeline.config)

@app.post("/api/config", tags=["配置"])
async def update_config(config: Dict[str, Any]):
    """更新配置"""
    if not pipeline:
        raise HTTPException(503, "流水线未初始化")

    pipeline.config.update(config)

    try:
        pipeline._init_components()
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
