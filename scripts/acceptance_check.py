"""One-click acceptance check for the data cleaning RAG tool.

This script intentionally uses the local dev config by default:
- hash embeddings
- memory vector DB
- bundled complex sample corpus

It writes both JSON and Markdown reports under reports/acceptance/.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.io import LoaderOptions, get_loader_diagnostics, load_documents_from_path
from src.pipeline import DataPipeline


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def run_command(args: List[str], timeout: int = 180) -> Dict[str, Any]:
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            args,
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
        output = proc.stdout
        return {
            "command": args,
            "passed": proc.returncode == 0,
            "returncode": proc.returncode,
            "duration_seconds": round(time.perf_counter() - started, 3),
            "output_tail": output[-4000:],
        }
    except Exception as exc:
        return {
            "command": args,
            "passed": False,
            "returncode": None,
            "duration_seconds": round(time.perf_counter() - started, 3),
            "output_tail": str(exc),
        }


def load_samples(paths: List[Path]) -> Dict[str, Any]:
    texts: List[str] = []
    metadatas: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []

    options = LoaderOptions(text_fields=["data.body"], max_records=500)
    for path in paths:
        if not path.exists():
            errors.append({"path": str(path), "error": "path does not exist"})
            continue
        try:
            file_texts, file_metadatas = load_documents_from_path(str(path), options=options)
            texts.extend(file_texts)
            metadatas.extend(file_metadatas)
        except Exception as exc:
            errors.append({"path": str(path), "error": str(exc)})

    return {
        "texts": texts,
        "metadatas": metadatas,
        "errors": errors,
        "file_types": sorted({metadata.get("file_type") for metadata in metadatas if metadata.get("file_type")}),
    }


def run_pipeline_acceptance(config: str, sample_paths: List[Path], query: str) -> Dict[str, Any]:
    loaded = load_samples(sample_paths)
    pipeline = DataPipeline(config)
    pipeline.init_vector_db("memory")
    metadata_db_config = pipeline.config.get("metadata_db", {})
    metadata_store_status = pipeline.metadata_store.health()

    stats: Dict[str, Any] = {}
    results: List[Dict[str, Any]] = []
    error: Optional[str] = None
    try:
        stats = pipeline.process_texts(loaded["texts"], source_metadata=loaded["metadatas"])
        results = pipeline.search(query, top_k=5) if stats.get("stored_count", 0) else []
    except Exception as exc:
        error = str(exc)
    finally:
        pipeline.close()

    report = stats.get("processing_report", {}) if stats else {}
    parent_child = report.get("parent_child", {})
    has_parent_context = any(
        bool((result.get("metadata") or {}).get("parent_context"))
        for result in results
    )
    has_child_id = any(
        bool((result.get("metadata") or {}).get("child_id"))
        for result in results
    )

    required_types = {".md", ".csv", ".jsonl", ".txt", ".html"}
    observed_types = set(loaded["file_types"])
    checks = {
        "sample_loads_without_errors": not loaded["errors"],
        "sample_document_count": len(loaded["texts"]) >= 8,
        "required_file_types_present": required_types.issubset(observed_types),
        "pipeline_stored_chunks": stats.get("stored_count", 0) > 0,
        "parent_child_enabled": parent_child.get("enabled") is True,
        "parent_child_counts_present": parent_child.get("parent_count", 0) > 0 and parent_child.get("child_count", 0) > 0,
        "search_returns_results": len(results) > 0,
        "search_returns_parent_context": has_parent_context,
        "search_returns_child_id": has_child_id,
        "route_a_metadata_config_present": metadata_db_config.get("type") in {"mysql", "sqlite"},
    }

    return {
        "passed": all(checks.values()) and error is None,
        "checks": checks,
        "error": error,
        "loaded": {
            "document_count": len(loaded["texts"]),
            "file_types": loaded["file_types"],
            "errors": loaded["errors"],
            "sample_paths": [str(path) for path in sample_paths],
        },
        "stats": stats,
        "metadata_db": {
            "config": {
                "enabled": metadata_db_config.get("enabled", False),
                "type": metadata_db_config.get("type", "disabled"),
            },
            "store": metadata_store_status,
        },
        "search": {
            "query": query,
            "result_count": len(results),
            "top_results": [
                {
                    "id": result.get("id"),
                    "score": result.get("score"),
                    "text_preview": (result.get("text") or "")[:160],
                    "metadata": {
                        key: (result.get("metadata") or {}).get(key)
                        for key in (
                            "filename",
                            "file_type",
                            "parent_id",
                            "child_id",
                            "parent_type",
                            "parent_heading_path",
                            "parent_section_title",
                        )
                    },
                    "has_parent_context": bool((result.get("metadata") or {}).get("parent_context")),
                }
                for result in results[:3]
            ],
        },
    }


def run_metadata_store_acceptance(config: str, sample_paths: List[Path]) -> Dict[str, Any]:
    """Verify route-A metadata persistence without requiring a live MySQL service."""
    loaded = load_samples(sample_paths)
    error: Optional[str] = None
    stats: Dict[str, Any] = {}
    run: Optional[Dict[str, Any]] = None
    recent_runs: List[Dict[str, Any]] = []

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(config)
            if not config_path.is_absolute():
                config_path = ROOT / config_path

            config_data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            config_data["metadata_db"] = {
                "enabled": True,
                "type": "sqlite",
                "fail_on_error": True,
                "sqlite": {
                    "path": str(Path(temp_dir) / "metadata.acceptance.sqlite3")
                },
            }
            metadata_config_path = Path(temp_dir) / "config.metadata.yaml"
            metadata_config_path.write_text(
                yaml.safe_dump(config_data, allow_unicode=True),
                encoding="utf-8",
            )

            pipeline = DataPipeline(str(metadata_config_path))
            pipeline.init_vector_db("memory")
            try:
                stats = pipeline.process_texts(
                    loaded["texts"],
                    source_metadata=loaded["metadatas"],
                )
                run_id = stats.get("metadata_run_id")
                run = pipeline.metadata_store.get_run(run_id) if run_id else None
                recent_runs = pipeline.metadata_store.get_recent_runs(limit=5)
            finally:
                pipeline.close()
    except Exception as exc:
        error = str(exc)

    run_chunks = (run or {}).get("chunks", [])
    checks = {
        "metadata_sqlite_enabled_for_acceptance": error is None,
        "metadata_run_id_present": bool(stats.get("metadata_run_id")),
        "metadata_run_persisted": bool(run),
        "metadata_recent_runs_query": len(recent_runs) > 0,
        "metadata_chunk_audit_persisted": len(run_chunks) == stats.get("chunked_count", 0) and len(run_chunks) > 0,
    }

    return {
        "passed": all(checks.values()) and error is None,
        "checks": checks,
        "error": error,
        "run_id": stats.get("metadata_run_id"),
        "stored_count": stats.get("stored_count", 0),
        "chunked_count": stats.get("chunked_count", 0),
        "persisted_chunk_count": len(run_chunks),
        "recent_run_count": len(recent_runs),
    }


def render_markdown(result: Dict[str, Any]) -> str:
    pipeline = result["pipeline"]
    metadata_acceptance = result.get("metadata_acceptance", {})
    stats = pipeline.get("stats", {})
    processing_report = stats.get("processing_report", {})
    summary = processing_report.get("summary", {})
    parent_child = processing_report.get("parent_child", {})
    quality = processing_report.get("quality_summary", {})
    metadata_db = pipeline.get("metadata_db", {})
    metadata_db_config = metadata_db.get("config", {})
    metadata_db_store = metadata_db.get("store", {})

    lines = [
        "# 数据清洗工具验收报告",
        "",
        f"- 生成时间: {result['generated_at']}",
        f"- 总体结论: {'通过' if result['passed'] else '未通过'}",
        f"- 配置文件: `{result['config']}`",
        f"- 样例路径: {', '.join(f'`{path}`' for path in pipeline['loaded']['sample_paths'])}",
        "",
        "## 自动检查结果",
        "",
        "| 检查项 | 结果 |",
        "|---|---|",
    ]
    for name, passed in pipeline["checks"].items():
        lines.append(f"| `{name}` | {'PASS' if passed else 'FAIL'} |")

    lines.extend([
        "",
        "## 处理统计",
        "",
        f"- 输入文档数: {summary.get('input_count', stats.get('input_count', 0))}",
        f"- 清洗后: {summary.get('cleaned_count', stats.get('cleaned_count', 0))}",
        f"- 过滤后: {summary.get('filtered_count', stats.get('filtered_count', 0))}",
        f"- 去重后: {summary.get('deduped_count', stats.get('deduped_count', 0))}",
        f"- 生成 chunk: {summary.get('chunked_count', stats.get('chunked_count', 0))}",
        f"- 入库 chunk: {summary.get('stored_count', stats.get('stored_count', 0))}",
        "",
        "## 父子 Chunk",
        "",
        f"- 启用: {parent_child.get('enabled')}",
        f"- 父 chunk 数: {parent_child.get('parent_count')}",
        f"- 子 chunk 数: {parent_child.get('child_count')}",
        f"- 父上下文字符数: {parent_child.get('parent_context_chars')}",
        "",
        "## Route A Metadata DB",
        "",
        f"- 配置存在: {metadata_db_config.get('type') in {'mysql', 'sqlite'}}",
        f"- 默认启用: {metadata_db_config.get('enabled')}",
        f"- 类型: {metadata_db_config.get('type')}",
        f"- 当前状态: {metadata_db_store.get('status')}",
        "",
        "## 质量过滤",
        "",
        f"- 评分数: {quality.get('scored_count')}",
        f"- 拒绝数: {quality.get('rejected_count')}",
        f"- 平均分: {quality.get('average_score')}",
        f"- 原因统计: `{json.dumps(quality.get('reason_counts', {}), ensure_ascii=False)}`",
        "",
        "## 搜索验证",
        "",
        f"- 查询: `{pipeline['search']['query']}`",
        f"- 返回结果数: {pipeline['search']['result_count']}",
        "",
        "| # | score | 文件 | 父类型 | 有父上下文 | 文本预览 |",
        "|---|---:|---|---|---|---|",
    ])
    for index, item in enumerate(pipeline["search"]["top_results"], start=1):
        metadata = item.get("metadata", {})
        preview = (item.get("text_preview") or "").replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| {index} | {item.get('score')} | {metadata.get('filename')} | "
            f"{metadata.get('parent_type')} | {item.get('has_parent_context')} | {preview} |"
        )

    lines.extend([
        "",
        "## 命令检查",
        "",
        f"- 单元测试: {'PASS' if result['unit_tests']['passed'] else 'FAIL'}",
        f"- 前端 JS: {'PASS' if result['node_check']['passed'] else 'SKIP/FAIL'}",
        f"- Metadata DB 写入链路: {'PASS' if metadata_acceptance.get('passed') else 'FAIL'}",
        "",
        "## Metadata DB 写入链路",
        "",
        "| 检查项 | 结果 |",
        "|---|---|",
    ])
    for name, passed in metadata_acceptance.get("checks", {}).items():
        lines.append(f"| `{name}` | {'PASS' if passed else 'FAIL'} |")
    lines.extend([
        "",
        f"- run_id: `{metadata_acceptance.get('run_id')}`",
        f"- 入库 chunk: {metadata_acceptance.get('stored_count')}",
        f"- 持久化 chunk 审计: {metadata_acceptance.get('persisted_chunk_count')}",
        "",
        "## 已知限制",
        "",
        "- 本验收默认使用 `config.dev.yaml`、hash embedding 和 memory 向量库，不代表生产向量库性能。",
        "- OCR 需要系统安装 Tesseract/Poppler 后再用扫描 PDF 和图片单独验收。",
        "- Route A 已支持独立 metadata_db：MySQL 存业务 metadata/处理批次/文件报告/chunk 审计，向量库继续负责向量检索；本验收默认不连接真实 MySQL。",
    ])
    return "\n".join(lines) + "\n"


def default_sample_paths() -> List[Path]:
    paths = [ROOT / "test_files" / "complex_samples"]
    docx = ROOT / "test_files" / "complex_rag_test_document.docx"
    if docx.exists():
        paths.append(docx)
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one-click acceptance checks.")
    parser.add_argument("--config", default="config.dev.yaml", help="Pipeline config path")
    parser.add_argument("--sample-path", action="append", help="Sample file or directory. Can repeat.")
    parser.add_argument("--query", default="付款条件 父子 chunk OCR 噪声", help="Search query used during acceptance")
    parser.add_argument("--output-dir", default="reports/acceptance", help="Directory for JSON and Markdown reports")
    parser.add_argument("--skip-unit-tests", action="store_true", help="Skip unittest discovery")
    parser.add_argument("--skip-node-check", action="store_true", help="Skip frontend JS syntax check")
    args = parser.parse_args()

    sample_paths = [Path(path) for path in args.sample_path] if args.sample_path else default_sample_paths()
    sample_paths = [path if path.is_absolute() else ROOT / path for path in sample_paths]

    unit_tests = (
        {"passed": True, "skipped": True, "output_tail": "skipped"}
        if args.skip_unit_tests
        else run_command([sys.executable, "-m", "unittest", "discover", "-s", "tests"], timeout=240)
    )

    if args.skip_node_check:
        node_check = {"passed": True, "skipped": True, "output_tail": "skipped"}
    elif shutil.which("node"):
        node_check = run_command(["node", "--check", "frontend/app.js"], timeout=60)
    else:
        node_check = {"passed": False, "skipped": True, "output_tail": "node executable not found"}

    pipeline = run_pipeline_acceptance(args.config, sample_paths, args.query)
    metadata_acceptance = run_metadata_store_acceptance(args.config, sample_paths)
    diagnostics = get_loader_diagnostics()

    result = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "config": args.config,
        "passed": bool(
            unit_tests["passed"]
            and node_check["passed"]
            and pipeline["passed"]
            and metadata_acceptance["passed"]
        ),
        "unit_tests": unit_tests,
        "node_check": node_check,
        "pipeline": pipeline,
        "metadata_acceptance": metadata_acceptance,
        "diagnostics": diagnostics,
    }

    output_dir = ROOT / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = now_stamp()
    json_path = output_dir / f"acceptance_{stamp}.json"
    md_path = output_dir / f"acceptance_{stamp}.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(result), encoding="utf-8")

    print(f"Acceptance result: {'PASS' if result['passed'] else 'FAIL'}")
    print(f"JSON report: {json_path}")
    print(f"Markdown report: {md_path}")
    if not result["passed"]:
        print("Failed checks:")
        for name, passed in pipeline["checks"].items():
            if not passed:
                print(f"  - {name}")
        if not unit_tests["passed"]:
            print("  - unit_tests")
        if not node_check["passed"]:
            print("  - node_check")
        for name, passed in metadata_acceptance["checks"].items():
            if not passed:
                print(f"  - {name}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
