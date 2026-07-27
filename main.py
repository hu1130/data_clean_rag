"""
数据清洗 + 向量数据库项目
主入口文件

使用方法:
    python main.py --config config.yaml --input data/raw/ --db chroma
"""

import argparse
import json
import os
import sys
import logging
from pathlib import Path

# 添加 src 到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.pipeline import DataPipeline
from src.ingestion import compute_content_hash, create_processing_manifest, file_key_for
from src.io import (
    LoaderOptions,
    SUPPORTED_EXTENSIONS,
    get_loader_diagnostics,
    load_documents_from_bytes,
    load_documents_from_path,
)


def setup_logging(config_path: str = "config.yaml"):
    """设置日志"""
    import yaml

    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    log_config = config.get('logging', {})
    level = getattr(logging, log_config.get('level', 'INFO'))
    log_file = log_config.get('file', 'logs/app.log')

    # 自动创建日志目录
    log_dir = os.path.dirname(log_file)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)

    logging.basicConfig(
        level=level,
        format=log_config.get('format', '%(asctime)s - %(name)s - %(levelname)s - %(message)s'),
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )


def iter_input_files(input_path: str):
    path = Path(input_path)
    if path.is_file():
        return [path]
    return sorted(
        file_path
        for file_path in path.rglob("*")
        if file_path.is_file() and file_path.suffix.lower() in SUPPORTED_EXTENSIONS
    )


def find_file_report(stats, update):
    reports = stats.get("processing_report", {}).get("files", [])
    for report in reports:
        if report.get("file_key") == update["file_key"] or report.get("file") == update["file_key"]:
            return report
        if report.get("filename") == update["filename"] and report.get("file_hash") == update["content_hash"]:
            return report
    return {}


def load_documents_incremental(input_path, loader_options, manifest, force_reprocess=False):
    texts = []
    metadatas = []
    skipped_files = []
    manifest_updates = []

    for file_path in iter_input_files(input_path):
        content = file_path.read_bytes()
        filename = file_path.name
        source_file = str(file_path.resolve())
        file_key = file_key_for(filename, source_file)
        content_hash = compute_content_hash(content)
        old_record = manifest.get(file_key)

        if not force_reprocess and manifest.is_unchanged(file_key, content_hash):
            skipped_files.append({
                "file": file_key,
                "file_key": file_key,
                "filename": filename,
                "content_hash": content_hash,
                "reason": "unchanged",
                "status": "skipped",
                "previous_chunk_count": (old_record or {}).get("chunk_count", 0),
            })
            continue

        base_metadata = {
            "source_file": source_file,
            "file_type": file_path.suffix.lower(),
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
        manifest_updates.append({
            "filename": filename,
            "file_key": file_key,
            "file_type": file_path.suffix.lower(),
            "content_hash": content_hash,
            "size_bytes": len(content),
            "document_count": len(file_texts),
            "old_chunk_ids": list((old_record or {}).get("chunk_ids") or []),
            "source_file": source_file,
        })

    return texts, metadatas, manifest_updates, skipped_files


def update_manifest_from_stats(manifest, stats, manifest_updates):
    for update in manifest_updates:
        report = find_file_report(stats, update)
        manifest.mark_processed(
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
    manifest.save()

def main():
    parser = argparse.ArgumentParser(description='数据清洗 + 向量数据库工具')
    parser.add_argument('--config', default='config.yaml', help='配置文件路径')
    parser.add_argument('--input', help='输入数据目录或文件')
    parser.add_argument('--db', default=None, choices=['memory', 'chroma', 'qdrant'], help='向量数据库类型')
    parser.add_argument('--query', help='搜索查询（可选）')
    parser.add_argument('--check-env', action='store_true', help='检查复杂文件解析、OCR 和依赖可用性后退出')
    parser.add_argument('--preview', action='store_true', help='只预览清洗和分块结果，不生成向量、不入库')
    parser.add_argument('--preview-limit', type=int, default=5, help='预览最多显示的文本块数量')
    parser.add_argument('--text-field', action='append', help='JSON/CSV 文本字段，可重复；支持 data.body 这种嵌套字段')
    parser.add_argument('--max-file-size-mb', type=int, default=100, help='单文件最大大小限制')
    parser.add_argument('--max-records', type=int, help='每个结构化文件最多读取的记录数')
    parser.add_argument('--excel-header-row', type=int, help='Excel 表头起始行，默认自动使用第一个非空行')
    parser.add_argument('--excel-header-rows', type=int, default=1, help='Excel 表头占用行数，用于多级表头')
    parser.add_argument('--excel-sheet-documents', action='store_true', help='Excel 按 sheet 合并为文档，而不是默认按数据行拆分')
    parser.add_argument('--no-docx-split-by-heading', action='store_true', help='DOCX 不按标题层级拆分')
    parser.add_argument('--no-pdf-infer-sections', action='store_true', help='PDF 不从页面文本推断章节标题')
    parser.add_argument('--ocr', action='store_true', help='启用 OCR 处理扫描 PDF 或图片文件')
    parser.add_argument('--ocr-backend', default='tesseract', help='OCR 后端，默认 tesseract')
    parser.add_argument('--ocr-language', default='eng', help='OCR 语言，默认 eng；中文可使用 chi_sim+eng')
    parser.add_argument('--ocr-dpi', type=int, default=200, help='PDF OCR 渲染 DPI')
    parser.add_argument('--ocr-max-pages', type=int, help='最多 OCR 的 PDF 空文本页数')

    parser.add_argument('--no-incremental', action='store_true', help='Disable manifest-based incremental ingestion')
    parser.add_argument('--force-reprocess', action='store_true', help='Reprocess files even when their hash is unchanged')
    parser.add_argument('--manifest-path', help='Incremental ingestion manifest path')
    parser.add_argument('--manifest-backend', choices=['auto', 'json', 'sqlite'], default='auto', help='Incremental manifest backend')

    args = parser.parse_args()

    if args.check_env:
        print(json.dumps(get_loader_diagnostics(), ensure_ascii=False, indent=2))
        return

    if not args.input:
        parser.error('--input is required unless --check-env is used')

    # 设置日志
    setup_logging(args.config)
    logger = logging.getLogger(__name__)

    logger.info("=" * 50)
    logger.info("数据清洗 + 向量数据库流水线启动")
    logger.info("=" * 50)

    # 初始化流水线
    pipeline = DataPipeline(config_path=args.config)
    if not args.preview:
        pipeline.init_vector_db(db_type=args.db)

    # 加载数据
    if not os.path.exists(args.input):
        os.makedirs(args.input, exist_ok=True)
        logger.info(f"创建输入目录: {args.input}")
        logger.info("请将文本文件放入该目录后重新运行")
        return

    loader_options = LoaderOptions(
        text_fields=args.text_field,
        max_file_size_mb=args.max_file_size_mb,
        max_records=args.max_records,
        excel_header_row=args.excel_header_row,
        excel_header_rows=args.excel_header_rows,
        excel_row_documents=not args.excel_sheet_documents,
        docx_split_by_heading=not args.no_docx_split_by_heading,
        pdf_infer_sections=not args.no_pdf_infer_sections,
        ocr_enabled=args.ocr,
        ocr_backend=args.ocr_backend,
        ocr_language=args.ocr_language,
        ocr_dpi=args.ocr_dpi,
        ocr_max_pages=args.ocr_max_pages,
    )
    ingestion_config = pipeline.config.get("ingestion", {})
    incremental_enabled = (
        ingestion_config.get("incremental", True)
        and not args.no_incremental
        and not args.preview
    )
    manifest = None
    manifest_updates = []
    skipped_files = []
    if incremental_enabled:
        manifest_path = args.manifest_path or ingestion_config.get("manifest_path", "data/manifest.sqlite3")
        manifest_backend = args.manifest_backend or ingestion_config.get("manifest_backend", "auto")
        manifest = create_processing_manifest(manifest_path, backend=manifest_backend)
        texts, metadatas, manifest_updates, skipped_files = load_documents_incremental(
            args.input,
            loader_options,
            manifest,
            force_reprocess=args.force_reprocess,
        )
        logger.info(
            f"Loaded {len(texts)} documents, skipped {len(skipped_files)} unchanged files"
        )
    else:
        texts, metadatas = load_documents_from_path(args.input, options=loader_options)

    if not texts and skipped_files:
        logger.info(f"All files unchanged, skipped {len(skipped_files)} files")
        return
    logger.info(f"加载了 {len(texts)} 个文档")

    if args.preview:
        prepared = pipeline.prepare_texts(
            texts,
            source_metadata=metadatas,
            mutate_dedup=False,
            max_preview_chars=300
        )
        logger.info("=" * 50)
        logger.info("预览统计:")
        for key, value in prepared['stats'].items():
            logger.info(f"  {key}: {value}")
        logger.info("=" * 50)

        for i, chunk in enumerate(prepared['chunks'][:args.preview_limit], start=1):
            logger.info(f"\n预览块 {i}:")
            logger.info(f"  metadata: {chunk.get('metadata', {})}")
            logger.info(f"  text: {chunk.get('text', '')}")
        return

    # 处理数据
    if incremental_enabled and pipeline.vector_db:
        deleted_vector_count = 0
        for update in manifest_updates:
            old_chunk_ids = update.get("old_chunk_ids") or []
            if old_chunk_ids:
                pipeline.vector_db.delete(old_chunk_ids)
                deleted_vector_count += len(old_chunk_ids)
        if deleted_vector_count:
            logger.info(f"Deleted {deleted_vector_count} old vectors before reprocessing")

    stats = pipeline.process_texts(texts, metadatas)
    if incremental_enabled and manifest is not None:
        if skipped_files:
            stats.setdefault("processing_report", {})["skipped_files"] = skipped_files
        update_manifest_from_stats(manifest, stats, manifest_updates)
        logger.info(f"Updated incremental manifest for {len(manifest_updates)} files")

    logger.info("=" * 50)
    logger.info("处理完成！统计信息:")
    for key, value in stats.items():
        logger.info(f"  {key}: {value}")
    logger.info("=" * 50)

    # 搜索演示
    if args.query:
        logger.info(f"执行搜索: {args.query}")
        results = pipeline.search(args.query, top_k=5)
        for i, result in enumerate(results):
            logger.info(f"\n结果 {i+1}:")
            logger.info(f"  ID: {result['id']}")
            logger.info(f"  相似度: {result.get('distance', result.get('score', 'N/A'))}")
            logger.info(f"  文本: {result['text'][:200]}...")

    # 关闭资源
    pipeline.close()
    logger.info("程序结束")


if __name__ == '__main__':
    main()
