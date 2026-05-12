"""
数据清洗 + 向量数据库主流水线
整合所有模块，提供端到端的数据处理流程
"""

import os
import yaml
from typing import List, Dict, Any, Optional
from pathlib import Path
import logging

# 导入各模块
from src.cleaning.text_cleaner import TextCleaner, QualityFilter
from src.cleaning.deduplicator import DedupPipeline
from src.chunking.chunkers import ChunkingPipeline
from src.embedding.models import EmbeddingModel
from src.vector_db.adapters import VectorDBFactory, BaseVectorDB

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
            batch_size=embedding_config.get('batch_size', 32)
        )

        # 向量数据库
        self.vector_db: Optional[BaseVectorDB] = None

    def init_vector_db(self, db_type: Optional[str] = None, **kwargs):
        """初始化向量数据库"""
        db_config = self.config.get('vector_db', {})
        db_type = db_type or db_config.get('type', 'chroma')

        # 获取对应类型的配置
        type_config = db_config.get(db_type, {})
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

    def process_texts(self, texts: List[str], source_metadata: Optional[List[Dict]] = None) -> Dict[str, Any]:
        """
        处理文本并入库

        Args:
            texts: 原始文本列表
            source_metadata: 每条文本的元数据

        Returns:
            处理统计信息
        """
        stats = {
            'input_count': len(texts),
            'cleaned_count': 0,
            'filtered_count': 0,
            'deduped_count': 0,
            'chunked_count': 0,
            'stored_count': 0
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
        logger.info(f"清洗后: {stats['cleaned_count']} 条")

        # 2. 质量过滤（保留索引映射）
        logger.info("开始质量过滤...")
        filtered_items = []
        for text, orig_idx in zip(cleaned_texts, cleaned_indices):
            if self.quality_filter.is_valid(text):
                filtered_items.append((text, orig_idx))

        filtered_texts = [item[0] for item in filtered_items]
        filtered_indices = [item[1] for item in filtered_items]
        stats['filtered_count'] = len(filtered_texts)
        logger.info(f"过滤后: {stats['filtered_count']} 条")

        # 3. 去重（保留索引映射）
        if self.config.get('data_cleaning', {}).get('deduplication', {}).get('enabled', True):
            logger.info("开始去重...")
            deduped_texts = self.dedup_pipeline.process(filtered_texts)
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
        chunked_results = self.chunking_pipeline.process(deduped_texts)
        stats['chunked_count'] = len(chunked_results)
        logger.info(f"分块后: {stats['chunked_count']} 块")

        # 5. 生成嵌入向量
        logger.info("开始生成嵌入向量...")
        chunk_texts = [item['text'] for item in chunked_results]
        embeddings = self.embedding_model.encode(chunk_texts)
        logger.info(f"嵌入向量生成完成: {len(embeddings)} 个")

        # 6. 存入向量数据库
        if self.vector_db:
            logger.info("开始存入向量数据库...")
            chunk_metadatas = [item['metadata'] for item in chunked_results]

            # 合并源元数据（使用原始索引映射）
            if source_metadata:
                for i, meta in enumerate(chunk_metadatas):
                    chunk_source_idx = meta.get('source_doc_id', 0)
                    if chunk_source_idx < len(deduped_indices):
                        original_idx = deduped_indices[chunk_source_idx]
                        if original_idx < len(source_metadata):
                            meta.update(source_metadata[original_idx])

            self.vector_db.add_vectors(
                vectors=embeddings.tolist(),
                texts=chunk_texts,
                metadatas=chunk_metadatas
            )
            stats['stored_count'] = len(chunk_texts)
            logger.info(f"成功存储 {stats['stored_count']} 个向量")

        return stats

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """语义搜索"""
        if not self.vector_db:
            raise ValueError("向量数据库未初始化")

        query_embedding = self.embedding_model.encode_single(query)
        results = self.vector_db.search(
            query_vector=query_embedding.tolist(),
            top_k=top_k
        )
        return results

    def get_stats(self) -> Dict[str, Any]:
        """获取数据库统计信息"""
        if self.vector_db:
            return self.vector_db.get_collection_info()
        return {}

    def close(self):
        """关闭资源"""
        if self.vector_db:
            self.vector_db.close()
