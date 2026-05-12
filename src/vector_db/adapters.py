"""
向量数据库统一接口
支持 ChromaDB、Milvus、Qdrant、Weaviate
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Tuple
import numpy as np
import logging
import uuid

logger = logging.getLogger(__name__)


class BaseVectorDB(ABC):
    """向量数据库抽象基类"""

    @abstractmethod
    def connect(self, **kwargs):
        """连接数据库"""
        pass

    @abstractmethod
    def create_collection(self, name: str, dimension: int, **kwargs):
        """创建集合"""
        pass

    @abstractmethod
    def add_vectors(
        self, 
        vectors: List[List[float]], 
        texts: List[str], 
        metadatas: Optional[List[Dict]] = None,
        ids: Optional[List[str]] = None
    ):
        """添加向量"""
        pass

    @abstractmethod
    def search(
        self, 
        query_vector: List[float], 
        top_k: int = 10,
        filter_dict: Optional[Dict] = None
    ) -> List[Dict[str, Any]]:
        """向量搜索"""
        pass

    @abstractmethod
    def delete(self, ids: List[str]):
        """删除向量"""
        pass

    @abstractmethod
    def get_collection_info(self) -> Dict[str, Any]:
        """获取集合信息"""
        pass

    @abstractmethod
    def close(self):
        """关闭连接"""
        pass


class ChromaDBAdapter(BaseVectorDB):
    """ChromaDB 适配器 - 适合原型开发和小规模生产"""

    def __init__(self, persist_directory: str = "./chroma_db", collection_name: str = "documents"):
        self.persist_directory = persist_directory
        self.collection_name = collection_name
        self.client = None
        self.collection = None

    def connect(self, **kwargs):
        """连接 ChromaDB"""
        try:
            import chromadb
            from chromadb.config import Settings

            self.client = chromadb.PersistentClient(
                path=self.persist_directory,
                settings=Settings(anonymized_telemetry=False)
            )
            logger.info(f"ChromaDB 连接成功: {self.persist_directory}")
        except ImportError:
            raise ImportError("请安装 chromadb: pip install chromadb")

    def create_collection(self, name: str, dimension: int, **kwargs):
        """创建或获取集合"""
        self.collection = self.client.get_or_create_collection(
            name=name,
            metadata={"dimension": dimension, **kwargs}
        )
        logger.info(f"集合创建/获取成功: {name}")

    def add_vectors(
        self, 
        vectors: List[List[float]], 
        texts: List[str], 
        metadatas: Optional[List[Dict]] = None,
        ids: Optional[List[str]] = None
    ):
        """添加向量到 ChromaDB"""
        if ids is None:
            ids = [str(uuid.uuid4()) for _ in range(len(vectors))]

        if metadatas is None:
            metadatas = [{} for _ in range(len(vectors))]

        # 添加文本到 metadata
        for i, text in enumerate(texts):
            metadatas[i]['text'] = text

        self.collection.add(
            embeddings=vectors,
            documents=texts,
            metadatas=metadatas,
            ids=ids
        )
        logger.info(f"成功添加 {len(vectors)} 个向量")

    def search(
        self, 
        query_vector: List[float], 
        top_k: int = 10,
        filter_dict: Optional[Dict] = None
    ) -> List[Dict[str, Any]]:
        """向量搜索"""
        results = self.collection.query(
            query_embeddings=[query_vector],
            n_results=top_k,
            where=filter_dict,
            include=["documents", "metadatas", "distances"]
        )

        # 格式化结果
        formatted_results = []
        for i in range(len(results['ids'][0])):
            formatted_results.append({
                'id': results['ids'][0][i],
                'text': results['documents'][0][i],
                'metadata': results['metadatas'][0][i],
                'distance': results['distances'][0][i]
            })

        return formatted_results

    def delete(self, ids: List[str]):
        """删除向量"""
        self.collection.delete(ids=ids)
        logger.info(f"删除 {len(ids)} 个向量")

    def get_collection_info(self) -> Dict[str, Any]:
        """获取集合信息"""
        count = self.collection.count()
        return {
            "name": self.collection.name,
            "count": count,
            "metadata": self.collection.metadata
        }

    def close(self):
        """关闭连接（ChromaDB 不需要显式关闭）"""
        pass


class QdrantAdapter(BaseVectorDB):
    """Qdrant 适配器 - 高性能，适合生产环境"""

    def __init__(self, host: str = "localhost", port: int = 6333, collection_name: str = "documents"):
        self.host = host
        self.port = port
        self.collection_name = collection_name
        self.client = None

    def connect(self, **kwargs):
        """连接 Qdrant"""
        try:
            from qdrant_client import QdrantClient
            self.client = QdrantClient(host=self.host, port=self.port)
            logger.info(f"Qdrant 连接成功: {self.host}:{self.port}")
        except ImportError:
            raise ImportError("请安装 qdrant-client: pip install qdrant-client")

    def create_collection(self, name: str, dimension: int, **kwargs):
        """创建集合"""
        from qdrant_client.models import Distance, VectorParams

        self.client.recreate_collection(
            collection_name=name,
            vectors_config=VectorParams(size=dimension, distance=Distance.COSINE)
        )
        self.collection_name = name
        logger.info(f"Qdrant 集合创建成功: {name}")

    def add_vectors(
        self, 
        vectors: List[List[float]], 
        texts: List[str], 
        metadatas: Optional[List[Dict]] = None,
        ids: Optional[List[str]] = None
    ):
        """添加向量到 Qdrant"""
        from qdrant_client.models import PointStruct

        if ids is None:
            ids = [f"doc_{i}" for i in range(len(vectors))]

        if metadatas is None:
            metadatas = [{} for _ in range(len(vectors))]

        points = []
        for i, (vector, text, metadata) in enumerate(zip(vectors, texts, metadatas)):
            metadata['text'] = text
            points.append(PointStruct(
                id=ids[i],
                vector=vector,
                payload=metadata
            ))

        self.client.upsert(
            collection_name=self.collection_name,
            points=points
        )
        logger.info(f"成功添加 {len(vectors)} 个向量到 Qdrant")

    def search(
        self, 
        query_vector: List[float], 
        top_k: int = 10,
        filter_dict: Optional[Dict] = None
    ) -> List[Dict[str, Any]]:
        """向量搜索"""
        from qdrant_client.models import Filter

        search_filter = Filter(**filter_dict) if filter_dict else None

        results = self.client.search(
            collection_name=self.collection_name,
            query_vector=query_vector,
            limit=top_k,
            query_filter=search_filter,
            with_payload=True
        )

        return [
            {
                'id': str(result.id),
                'text': result.payload.get('text', ''),
                'metadata': result.payload,
                'score': result.score
            }
            for result in results
        ]

    def delete(self, ids: List[str]):
        """删除向量"""
        from qdrant_client.models import PointIdsList
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=PointIdsList(points=ids)
        )

    def get_collection_info(self) -> Dict[str, Any]:
        """获取集合信息"""
        info = self.client.get_collection(self.collection_name)
        return {
            "name": self.collection_name,
            "vectors_count": info.vectors_count,
            "status": info.status
        }

    def close(self):
        """关闭连接"""
        if self.client:
            self.client.close()


class VectorDBFactory:
    """向量数据库工厂"""

    _adapters = {
        'chroma': ChromaDBAdapter,
        'qdrant': QdrantAdapter,
    }

    @classmethod
    def create(cls, db_type: str, **kwargs) -> BaseVectorDB:
        """创建向量数据库适配器"""
        if db_type not in cls._adapters:
            raise ValueError(f"不支持的向量数据库类型: {db_type}")

        adapter_class = cls._adapters[db_type]
        return adapter_class(**kwargs)
