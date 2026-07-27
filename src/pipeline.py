"""
数据清洗 + 向量数据库主流水线
整合所有模块，提供端到端的数据处理流程
"""

import os
import yaml
import uuid
import hashlib
from typing import Callable, List, Dict, Any, Optional
from pathlib import Path
import logging

# 导入各模块
from src.cleaning.text_cleaner import TextCleaner, QualityFilter
from src.cleaning.deduplicator import DedupPipeline
from src.chunking.chunkers import ChunkingPipeline
from src.embedding.models import EmbeddingModel
from src.embedding.reranker import RerankerFactory
from src.vector_db.adapters import VectorDBFactory, BaseVectorDB
from src.metadata_store import BaseMetadataStore, create_metadata_store

logger = logging.getLogger(__name__)


class DataPipeline:
    """
    数据清洗 + 向量数据库流水线

    处理流程:
    1. 加载原始数据
    2. 文本清洗
    3. 质量过滤
    4. 去重
    5. 分块（可选）
    6. 生成嵌入向量
    7. 存入向量数据库
    """

    def __init__(self, config_path: str = "config.yaml"):
        self.config = self._load_config(config_path)
        self._init_components()

    def _load_config(self, path: str) -> Dict[str, Any]:
        """加载配置文件"""
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)

    def _init_components(self):
        """初始化各组件"""
        # 数据清洗
        cleaning_config = self.config.get('data_cleaning', {})
        self.text_cleaner = TextCleaner(cleaning_config)
        self.quality_filter = QualityFilter(cleaning_config.get('quality_filter', {}))

        # 去重
        dedup_config = cleaning_config.get('deduplication', {})
        self.dedup_pipeline = DedupPipeline(dedup_config)

        # 分块
        chunking_config = self.config.get('chunking', {})
        self.chunking_pipeline = ChunkingPipeline(chunking_config)

        # 嵌入模型
        embedding_config = self.config.get('embedding', {})
        self.embedding_model = EmbeddingModel(
            model_name=embedding_config.get('model_name', 'BAAI/bge-large-zh-v1.5'),
            device=embedding_config.get('device', 'auto'),
            batch_size=embedding_config.get('batch_size', 32),
            normalize_embeddings=embedding_config.get('normalize_embeddings', True),
            provider=embedding_config.get('provider'),
            api_key=embedding_config.get('api_key'),
            api_key_env=embedding_config.get('api_key_env', 'OPENAI_API_KEY'),
            dimension=embedding_config.get('dimension'),
        )

        # Reranker
        self.reranker_config = self.config.get('reranker', {})
        self.reranker = RerankerFactory.create(self.reranker_config)

        # 向量数据库
        self.vector_db: Optional[BaseVectorDB] = None
        self.metadata_store: BaseMetadataStore = create_metadata_store(
            self.config.get('metadata_db', {})
        )

    def _summarize_quality_reports(self, reports: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Build a compact quality summary for stats."""
        if not reports:
            return {
                'scored_count': 0,
                'rejected_count': 0,
                'average_score': 0,
                'reason_counts': {}
            }

        reason_counts: Dict[str, int] = {}
        score_total = 0
        rejected_count = 0
        for report in reports:
            score_total += report.get('score', 0)
            if not report.get('valid', False):
                rejected_count += 1
            for reason in report.get('reasons', []):
                reason_counts[reason] = reason_counts.get(reason, 0) + 1

        return {
            'scored_count': len(reports),
            'rejected_count': rejected_count,
            'average_score': round(score_total / len(reports), 2),
            'reason_counts': reason_counts
        }

    def _build_processing_report(
        self,
        stats: Dict[str, Any],
        source_metadata: Optional[List[Dict]],
        rejected_quality_reports: List[Dict[str, Any]],
        chunks: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Build a file-oriented processing report for audit/debugging."""
        report = {
            'summary': {
                key: stats.get(key, 0)
                for key in ('input_count', 'cleaned_count', 'filtered_count', 'deduped_count', 'chunked_count', 'stored_count')
            },
            'quality_summary': stats.get('quality_summary', {}),
            'embedding': self.embedding_model.info(),
            'reranker': {
                'enabled': self.reranker_config.get('enabled', False),
                'type': self.reranker_config.get('type', 'none'),
                'model_name': self.reranker_config.get('model_name'),
            },
            'document_part_counts': {},
            'files': {},
            'rejected_samples': rejected_quality_reports[:20],
        }

        for metadata in source_metadata or []:
            file_key = self._metadata_file_key(metadata)
            file_report = report['files'].setdefault(file_key, self._empty_file_report(file_key, metadata))
            file_report['input_documents'] += 1
            part = metadata.get('document_part', 'document')
            file_report['document_part_counts'][part] = file_report['document_part_counts'].get(part, 0) + 1
            report['document_part_counts'][part] = report['document_part_counts'].get(part, 0) + 1

        for chunk in chunks:
            metadata = chunk.get('metadata', {})
            file_key = self._metadata_file_key(metadata)
            file_report = report['files'].setdefault(file_key, self._empty_file_report(file_key, metadata))
            file_report['chunks'] += 1
            chunk_id = metadata.get('chunk_id')
            if chunk_id:
                file_report['chunk_ids'].append(chunk_id)

        parent_ids = {
            chunk.get('metadata', {}).get('parent_id')
            for chunk in chunks
            if chunk.get('metadata', {}).get('parent_id')
        }
        parent_child_config = self._parent_child_config()
        report['parent_child'] = {
            'enabled': parent_child_config.get('enabled', True),
            'parent_count': len(parent_ids),
            'child_count': len(chunks),
            'parent_context_chars': parent_child_config.get('parent_context_chars', 1200),
        }

        for rejection in rejected_quality_reports:
            metadata = rejection.get('metadata', {})
            file_key = self._metadata_file_key(metadata)
            file_report = report['files'].setdefault(file_key, self._empty_file_report(file_key, metadata))
            file_report['rejected_documents'] += 1
            for reason in rejection.get('reasons', []):
                file_report['rejection_reasons'][reason] = file_report['rejection_reasons'].get(reason, 0) + 1

        report['files'] = list(report['files'].values())
        return report

    def _metadata_file_key(self, metadata: Dict[str, Any]) -> str:
        return metadata.get('file_key') or metadata.get('source_file') or metadata.get('filename') or 'inline'

    def _parent_child_config(self) -> Dict[str, Any]:
        config = self.config.get('chunking', {}).get('parent_child', {})
        return {
            'enabled': config.get('enabled', True),
            'parent_context_chars': int(config.get('parent_context_chars', 1200)),
        }

    def _stable_parent_id(
        self,
        parent_text: str,
        metadata: Dict[str, Any],
        source_doc_id: int,
        original_index: Optional[int]
    ) -> str:
        file_hash = metadata.get('file_hash') or metadata.get('content_hash')
        content_key = file_hash or hashlib.sha256(parent_text.encode('utf-8')).hexdigest()
        raw = ":".join([
            str(content_key),
            str(self._metadata_file_key(metadata)),
            str(metadata.get('document_part', 'document')),
            str(metadata.get('heading_path') or metadata.get('section_title') or ''),
            str(metadata.get('page_number') or ''),
            str(metadata.get('sheet_name') or ''),
            str(metadata.get('row_number') or ''),
            str(original_index if original_index is not None else source_doc_id),
        ])
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"data-clean-rag-parent:{raw}"))

    def _parent_context(self, text: str, max_chars: int) -> str:
        if max_chars <= 0:
            return ''
        if len(text) <= max_chars:
            return text
        return text[:max_chars].rstrip() + "..."

    def _assign_parent_child_metadata(
        self,
        chunks: List[Dict[str, Any]],
        parent_texts: List[str],
        deduped_indices: List[int],
        source_metadata: Optional[List[Dict]]
    ):
        parent_child_config = self._parent_child_config()
        if not parent_child_config.get('enabled', True):
            return

        context_chars = parent_child_config.get('parent_context_chars', 1200)
        parent_cache: Dict[int, Dict[str, Any]] = {}

        for item in chunks:
            metadata = dict(item.get('metadata', {}))
            source_doc_id = metadata.get('source_doc_id', 0)
            try:
                source_doc_id = int(source_doc_id)
            except (TypeError, ValueError):
                source_doc_id = 0

            if source_doc_id < 0 or source_doc_id >= len(parent_texts):
                item['metadata'] = metadata
                continue

            if source_doc_id not in parent_cache:
                original_index = deduped_indices[source_doc_id] if source_doc_id < len(deduped_indices) else source_doc_id
                parent_source_meta = {}
                if source_metadata and original_index < len(source_metadata):
                    parent_source_meta = dict(source_metadata[original_index])

                parent_text = parent_texts[source_doc_id]
                parent_type = parent_source_meta.get('document_part') or (
                    'section' if parent_source_meta.get('heading_path') else 'document'
                )
                parent_cache[source_doc_id] = {
                    'parent_id': self._stable_parent_id(parent_text, parent_source_meta, source_doc_id, original_index),
                    'parent_type': parent_type,
                    'parent_source_doc_id': source_doc_id,
                    'parent_original_index': original_index,
                    'parent_char_count': len(parent_text),
                    'parent_context': self._parent_context(parent_text, context_chars),
                    'parent_heading_path': parent_source_meta.get('heading_path') or '',
                    'parent_section_title': parent_source_meta.get('section_title') or '',
                    'parent_file_key': self._metadata_file_key(parent_source_meta),
                }

            parent_metadata = parent_cache[source_doc_id]
            metadata.update({
                **parent_metadata,
                'child_index': metadata.get('chunk_index', 0),
                'child_count': metadata.get('total_chunks', 1),
                'retrieval_level': 'child',
                'retrieval_parent_child': True,
            })
            item['metadata'] = metadata

    def _empty_file_report(self, file_key: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        return {
            'file': file_key,
            'file_key': file_key,
            'filename': metadata.get('filename', file_key),
            'source_file': metadata.get('source_file'),
            'file_type': metadata.get('file_type'),
            'file_hash': metadata.get('file_hash') or metadata.get('content_hash'),
            'content_hash': metadata.get('content_hash') or metadata.get('file_hash'),
            'file_size_bytes': metadata.get('file_size_bytes'),
            'input_documents': 0,
            'chunks': 0,
            'chunk_ids': [],
            'rejected_documents': 0,
            'rejection_reasons': {},
            'document_part_counts': {},
        }

    def _assign_chunk_ids(self, chunks: List[Dict[str, Any]]) -> List[str]:
        vector_ids = []
        for fallback_index, item in enumerate(chunks):
            metadata = dict(item.get('metadata', {}))
            file_hash = metadata.get('file_hash') or metadata.get('content_hash')
            if file_hash:
                raw = ":".join([
                    str(file_hash),
                    str(metadata.get('file_key') or metadata.get('source_file') or metadata.get('filename') or 'inline'),
                    str(metadata.get('source_doc_id', 0)),
                    str(metadata.get('chunk_index', fallback_index)),
                ])
                chunk_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"data-clean-rag:{raw}"))
            else:
                chunk_id = str(uuid.uuid4())

            metadata['chunk_id'] = chunk_id
            metadata['child_id'] = chunk_id
            item['metadata'] = metadata
            vector_ids.append(chunk_id)
        return vector_ids

    def _emit_progress(
        self,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]],
        stage: str,
        percent: float,
        message: str,
        **extra: Any
    ):
        if not progress_callback:
            return
        payload = {
            'stage': stage,
            'percent': round(float(percent), 2),
            'message': message,
            **extra,
        }
        progress_callback(payload)

    def _record_metadata_run(
        self,
        stats: Dict[str, Any],
        chunks: List[Dict[str, Any]],
        status: str = 'completed'
    ):
        """Persist processing audit metadata when metadata_db is enabled."""
        metadata_store = getattr(self, 'metadata_store', None)
        if not metadata_store or not metadata_store.enabled:
            return

        run_id = stats.get('metadata_run_id') or str(uuid.uuid4())
        stats['metadata_run_id'] = run_id
        processing_report = stats.setdefault('processing_report', {})
        processing_report['metadata_store'] = {
            **metadata_store.health(),
            'run_id': run_id,
        }

        try:
            metadata_store.record_processing_run(
                stats,
                chunks,
                status=status,
                run_id=run_id,
            )
        except Exception as exc:
            if getattr(metadata_store, 'fail_on_error', True):
                raise
            stats['metadata_store_error'] = str(exc)
            processing_report['metadata_store']['status'] = 'error'
            processing_report['metadata_store']['error'] = str(exc)

    def init_vector_db(self, db_type: Optional[str] = None, **kwargs):
        """初始化向量数据库"""
        db_config = self.config.get('vector_db', {})
        db_type = db_type or db_config.get('type', 'chroma')

        # 获取对应类型的配置
        type_config = dict(db_config.get(db_type, {}))
        type_config.update(kwargs)

        self.vector_db = VectorDBFactory.create(db_type, **type_config)
        self.vector_db.connect()

        # 创建集合
        dimension = self.embedding_model.dimension
        self.vector_db.create_collection(
            name=type_config.get('collection_name', 'documents'),
            dimension=dimension
        )

        logger.info(f"向量数据库初始化完成: {db_type}")

    def process_texts(
        self,
        texts: List[str],
        source_metadata: Optional[List[Dict]] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None
    ) -> Dict[str, Any]:
        """
        处理文本并入库

        Args:
            texts: 原始文本列表
            source_metadata: 每条文本的元数据

        Returns:
            处理统计信息
        """
        self._emit_progress(progress_callback, 'starting', 1, 'Processing started', input_count=len(texts))
        prepared = self.prepare_texts(
            texts,
            source_metadata=source_metadata,
            progress_callback=progress_callback
        )
        stats = prepared['stats']
        chunked_results = prepared['chunks']
        chunk_texts = [item['text'] for item in chunked_results]
        vector_ids = [item.get('metadata', {}).get('chunk_id') for item in chunked_results]

        if not chunk_texts:
            self._record_metadata_run(stats, chunked_results)
            self._emit_progress(progress_callback, 'completed', 100, 'No chunks to store', stats=stats)
            logger.info("没有可入库的文本块，跳过嵌入和向量存储")
            return stats

        # 5. 生成嵌入向量
        logger.info("开始生成嵌入向量...")
        self._emit_progress(progress_callback, 'embedding', 80, 'Generating embeddings', chunk_count=len(chunk_texts))
        embeddings = self.embedding_model.encode(chunk_texts)
        logger.info(f"嵌入向量生成完成: {len(embeddings)} 个")

        # 6. 存入向量数据库
        if self.vector_db:
            logger.info("开始存入向量数据库...")
            chunk_metadatas = [dict(item['metadata']) for item in chunked_results]
            vectors = embeddings.tolist() if hasattr(embeddings, 'tolist') else embeddings
            self._emit_progress(progress_callback, 'storing', 92, 'Storing vectors', chunk_count=len(chunk_texts))
            self.vector_db.add_vectors(
                vectors=vectors,
                texts=chunk_texts,
                metadatas=chunk_metadatas,
                ids=vector_ids
            )
            stats['stored_count'] = len(chunk_texts)
            if 'processing_report' in stats:
                stats['processing_report']['summary']['stored_count'] = stats['stored_count']
            logger.info(f"成功存储 {stats['stored_count']} 个向量")

        self._record_metadata_run(stats, chunked_results)
        self._emit_progress(progress_callback, 'completed', 100, 'Processing completed', stats=stats)
        return stats

    def prepare_texts(
        self,
        texts: List[str],
        source_metadata: Optional[List[Dict]] = None,
        mutate_dedup: bool = True,
        max_preview_chars: Optional[int] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None
    ) -> Dict[str, Any]:
        """
        清洗、过滤、去重并分块，但不生成嵌入、不写入向量库。

        Args:
            texts: 原始文本列表
            source_metadata: 每条文本的元数据
            mutate_dedup: 是否使用当前流水线的去重器状态
            max_preview_chars: 预览时限制每个块返回的文本长度

        Returns:
            包含 stats 和 chunks 的字典
        """
        stats = {
            'input_count': len(texts),
            'cleaned_count': 0,
            'filtered_count': 0,
            'deduped_count': 0,
            'chunked_count': 0,
            'stored_count': 0,
            'quality_summary': {
                'scored_count': 0,
                'rejected_count': 0,
                'average_score': 0,
                'reason_counts': {}
            }
        }

        # 1. 文本清洗（保留原始索引映射）
        logger.info("开始文本清洗...")
        cleaned_items = []  # [(text, original_index), ...]
        for i, text in enumerate(texts):
            cleaned = self.text_cleaner.clean(text)
            if cleaned:
                cleaned_items.append((cleaned, i))

        cleaned_texts = [item[0] for item in cleaned_items]
        cleaned_indices = [item[1] for item in cleaned_items]
        stats['cleaned_count'] = len(cleaned_texts)
        self._emit_progress(progress_callback, 'cleaning', 15, 'Text cleaning completed', cleaned_count=stats['cleaned_count'])
        logger.info(f"清洗后: {stats['cleaned_count']} 条")

        # 2. 质量过滤（保留索引映射）
        logger.info("开始质量过滤...")
        filtered_items = []
        quality_reports = []
        rejected_quality_reports = []
        for text, orig_idx in zip(cleaned_texts, cleaned_indices):
            report = dict(self.quality_filter.score(text))
            report['original_index'] = orig_idx
            report['text_preview'] = text[:200]
            if source_metadata and orig_idx < len(source_metadata):
                report['metadata'] = dict(source_metadata[orig_idx])

            quality_reports.append(report)
            if report.get('valid', False):
                filtered_items.append((text, orig_idx))
            else:
                rejected_quality_reports.append(report)

        filtered_texts = [item[0] for item in filtered_items]
        filtered_indices = [item[1] for item in filtered_items]
        stats['filtered_count'] = len(filtered_texts)
        stats['quality_summary'] = self._summarize_quality_reports(quality_reports)
        self._emit_progress(progress_callback, 'quality_filter', 32, 'Quality filtering completed', filtered_count=stats['filtered_count'])
        logger.info(f"过滤后: {stats['filtered_count']} 条")

        # 3. 去重（保留索引映射）
        if self.config.get('data_cleaning', {}).get('deduplication', {}).get('enabled', True):
            logger.info("开始去重...")
            dedup_pipeline = self.dedup_pipeline
            if not mutate_dedup:
                dedup_config = self.config.get('data_cleaning', {}).get('deduplication', {})
                dedup_pipeline = DedupPipeline(dedup_config)

            deduped_texts = dedup_pipeline.process(filtered_texts)
            # 去重后需要重新建立索引映射（去重保留的文档顺序不变）
            # 使用 dict 快速查找保留的文档
            deduped_set = set(deduped_texts)
            deduped_items = [(text, idx) for text, idx in zip(filtered_texts, filtered_indices) if text in deduped_set]
            # 去重后可能还有重复（MinHash近似），再去一次重
            seen = set()
            final_items = []
            for text, idx in deduped_items:
                if text not in seen:
                    seen.add(text)
                    final_items.append((text, idx))
            deduped_texts = [item[0] for item in final_items]
            deduped_indices = [item[1] for item in final_items]
            stats['deduped_count'] = len(deduped_texts)
            logger.info(f"去重后: {stats['deduped_count']} 条")
        else:
            deduped_texts = filtered_texts
            deduped_indices = filtered_indices
            stats['deduped_count'] = len(deduped_texts)

        # 4. 分块
        logger.info("开始分块...")
        self._emit_progress(progress_callback, 'deduplication', 50, 'Deduplication completed', deduped_count=stats['deduped_count'])
        chunked_results = self.chunking_pipeline.process(deduped_texts)
        stats['chunked_count'] = len(chunked_results)
        self._emit_progress(progress_callback, 'chunking', 68, 'Chunking completed', chunked_count=stats['chunked_count'])
        logger.info(f"分块后: {stats['chunked_count']} 块")

        # 合并源元数据（使用原始索引映射）
        if source_metadata:
            for item in chunked_results:
                meta = dict(item.get('metadata', {}))
                chunk_source_idx = meta.get('source_doc_id', 0)
                if chunk_source_idx < len(deduped_indices):
                    original_idx = deduped_indices[chunk_source_idx]
                    if original_idx < len(source_metadata):
                        meta.update(source_metadata[original_idx])
                item['metadata'] = meta

        self._assign_parent_child_metadata(
            chunked_results,
            deduped_texts,
            deduped_indices,
            source_metadata
        )
        self._assign_chunk_ids(chunked_results)
        stats['processing_report'] = self._build_processing_report(
            stats,
            source_metadata,
            rejected_quality_reports,
            chunked_results
        )

        if max_preview_chars is not None:
            for item in chunked_results:
                item['text'] = item['text'][:max_preview_chars]

        return {
            'stats': stats,
            'chunks': chunked_results,
            'quality_reports': rejected_quality_reports
        }

    def search(
        self,
        query: str,
        top_k: int = 5,
        filter_dict: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """语义搜索"""
        if not self.vector_db:
            raise ValueError("向量数据库未初始化")

        query_embedding = self.embedding_model.encode_single(query)
        candidate_top_k = top_k
        if self.reranker_config.get('enabled', False):
            candidate_top_k = max(
                top_k,
                self.reranker_config.get('candidate_top_k', top_k * 5)
            )
        results = self.vector_db.search(
            query_vector=query_embedding.tolist(),
            top_k=candidate_top_k,
            filter_dict=filter_dict
        )
        return self.reranker.rerank(query, results, top_k=top_k)

    def get_stats(self) -> Dict[str, Any]:
        """获取数据库统计信息"""
        if self.vector_db:
            return self.vector_db.get_collection_info()
        return {}

    def reset_dedup_state(self):
        """重置去重器状态。"""
        self.dedup_pipeline.reset()

    def clear_vector_db(self, reset_dedup: bool = True):
        """清空向量数据库，并可同步重置去重状态。"""
        if not self.vector_db:
            raise ValueError("向量数据库未初始化")

        self.vector_db.clear()
        if reset_dedup:
            self.reset_dedup_state()

    def close(self):
        """关闭资源"""
        if self.vector_db:
            self.vector_db.close()
        metadata_store = getattr(self, 'metadata_store', None)
        if metadata_store:
            metadata_store.close()
