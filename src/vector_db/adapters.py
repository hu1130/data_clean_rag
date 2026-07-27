"""
向量数据库统一接口
支持 ChromaDB、Milvus、Qdrant、Weaviate
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Tuple
import numpy as np
import logging
import uuid
import json
import sqlite3
import time
from pathlib import Path

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

    def clear(self):
        """清空集合"""
        raise NotImplementedError("当前向量数据库不支持清空集合")

    @abstractmethod
    def close(self):
        """关闭连接"""
        pass


class MemoryVectorDBAdapter(BaseVectorDB):
    """内存向量数据库适配器 - 适合本地开发、测试和 API smoke test"""

    def __init__(self, collection_name: str = "documents"):
        self.collection_name = collection_name
        self.dimension = None
        self.ids: List[str] = []
        self.vectors: List[List[float]] = []
        self.texts: List[str] = []
        self.metadatas: List[Dict[str, Any]] = []

    def connect(self, **kwargs):
        logger.info("MemoryVectorDB 连接成功")

    def create_collection(self, name: str, dimension: int, **kwargs):
        self.collection_name = name
        self.dimension = dimension
        logger.info(f"MemoryVectorDB 集合就绪: {name}, dimension={dimension}")

    def add_vectors(
        self,
        vectors: List[List[float]],
        texts: List[str],
        metadatas: Optional[List[Dict]] = None,
        ids: Optional[List[str]] = None
    ):
        if ids is None:
            ids = [str(uuid.uuid4()) for _ in range(len(vectors))]

        if metadatas is None:
            metadatas = [{} for _ in range(len(vectors))]

        for vector, text, metadata, vector_id in zip(vectors, texts, metadatas, ids):
            if self.dimension is not None and len(vector) != self.dimension:
                raise ValueError(f"向量维度不匹配: expected={self.dimension}, actual={len(vector)}")

            payload = dict(metadata)
            payload['text'] = text
            self.ids.append(vector_id)
            self.vectors.append(vector)
            self.texts.append(text)
            self.metadatas.append(payload)

        logger.info(f"成功添加 {len(vectors)} 个向量到 MemoryVectorDB")

    def search(
        self,
        query_vector: List[float],
        top_k: int = 10,
        filter_dict: Optional[Dict] = None
    ) -> List[Dict[str, Any]]:
        if not self.vectors:
            return []

        query = np.array(query_vector, dtype=np.float32)
        query_norm = np.linalg.norm(query)
        if query_norm == 0:
            return []

        scored = []
        for vector_id, vector, text, metadata in zip(self.ids, self.vectors, self.texts, self.metadatas):
            if filter_dict and not all(metadata.get(key) == value for key, value in filter_dict.items()):
                continue

            candidate = np.array(vector, dtype=np.float32)
            candidate_norm = np.linalg.norm(candidate)
            if candidate_norm == 0:
                score = 0.0
            else:
                score = float(np.dot(query, candidate) / (query_norm * candidate_norm))

            scored.append({
                'id': vector_id,
                'text': text,
                'metadata': metadata,
                'score': score
            })

        scored.sort(key=lambda item: item['score'], reverse=True)
        return scored[:top_k]

    def delete(self, ids: List[str]):
        id_set = set(ids)
        kept = [
            (vector_id, vector, text, metadata)
            for vector_id, vector, text, metadata in zip(self.ids, self.vectors, self.texts, self.metadatas)
            if vector_id not in id_set
        ]

        self.ids = [item[0] for item in kept]
        self.vectors = [item[1] for item in kept]
        self.texts = [item[2] for item in kept]
        self.metadatas = [item[3] for item in kept]
        logger.info(f"删除 {len(ids)} 个向量")

    def clear(self):
        self.ids = []
        self.vectors = []
        self.texts = []
        self.metadatas = []
        logger.info("MemoryVectorDB 已清空")

    def get_collection_info(self) -> Dict[str, Any]:
        return {
            "name": self.collection_name,
            "dimension": self.dimension,
            "count": len(self.ids),
            "status": "active"
        }

    def close(self):
        pass


class SQLiteVectorDBAdapter(BaseVectorDB):
    """SQLite 持久化向量库 - 适合本地测试、小规模数据和无外部服务环境。"""

    def __init__(self, path: str = "data/vectors.sqlite3", collection_name: str = "documents"):
        self.path = path
        self.collection_name = collection_name
        self.dimension = None
        self.conn: Optional[sqlite3.Connection] = None

    def connect(self, **kwargs):
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS collections (
                name TEXT PRIMARY KEY,
                dimension INTEGER NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS vectors (
                collection_name TEXT NOT NULL,
                id TEXT NOT NULL,
                text TEXT NOT NULL,
                metadata TEXT NOT NULL,
                vector TEXT NOT NULL,
                created_at REAL NOT NULL,
                PRIMARY KEY (collection_name, id)
            )
            """
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_vectors_collection ON vectors(collection_name)"
        )
        self.conn.commit()
        logger.info(f"SQLiteVectorDB 连接成功: {self.path}")

    def create_collection(self, name: str, dimension: int, **kwargs):
        if not self.conn:
            raise ValueError("SQLiteVectorDB 未连接")
        self.collection_name = name
        self.dimension = dimension
        self.conn.execute(
            """
            INSERT INTO collections(name, dimension, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                dimension = excluded.dimension,
                updated_at = excluded.updated_at
            """,
            (name, dimension, time.time()),
        )
        self.conn.commit()
        logger.info(f"SQLiteVectorDB 集合就绪: {name}, dimension={dimension}")

    def add_vectors(
        self,
        vectors: List[List[float]],
        texts: List[str],
        metadatas: Optional[List[Dict]] = None,
        ids: Optional[List[str]] = None
    ):
        if not self.conn:
            raise ValueError("SQLiteVectorDB 未连接")
        if ids is None:
            ids = [str(uuid.uuid4()) for _ in range(len(vectors))]
        if metadatas is None:
            metadatas = [{} for _ in range(len(vectors))]

        rows = []
        for vector, text, metadata, vector_id in zip(vectors, texts, metadatas, ids):
            if self.dimension is not None and len(vector) != self.dimension:
                raise ValueError(f"向量维度不匹配: expected={self.dimension}, actual={len(vector)}")
            payload = dict(metadata)
            payload["text"] = text
            rows.append((
                self.collection_name,
                vector_id,
                text,
                json.dumps(payload, ensure_ascii=False),
                json.dumps([float(value) for value in vector], ensure_ascii=False),
                time.time(),
            ))

        self.conn.executemany(
            """
            INSERT INTO vectors(collection_name, id, text, metadata, vector, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(collection_name, id) DO UPDATE SET
                text = excluded.text,
                metadata = excluded.metadata,
                vector = excluded.vector,
                created_at = excluded.created_at
            """,
            rows,
        )
        self.conn.commit()
        logger.info(f"成功添加 {len(rows)} 个向量到 SQLiteVectorDB")

    def _iter_rows(self, filter_dict: Optional[Dict] = None):
        if not self.conn:
            raise ValueError("SQLiteVectorDB 未连接")
        cursor = self.conn.execute(
            """
            SELECT id, text, metadata, vector
            FROM vectors
            WHERE collection_name = ?
            """,
            (self.collection_name,),
        )
        for row in cursor:
            metadata = json.loads(row["metadata"] or "{}")
            if filter_dict and not all(metadata.get(key) == value for key, value in filter_dict.items()):
                continue
            yield row["id"], row["text"], metadata, json.loads(row["vector"])

    def search(
        self,
        query_vector: List[float],
        top_k: int = 10,
        filter_dict: Optional[Dict] = None
    ) -> List[Dict[str, Any]]:
        query = np.array(query_vector, dtype=np.float32)
        query_norm = np.linalg.norm(query)
        if query_norm == 0:
            return []

        scored = []
        for vector_id, text, metadata, vector in self._iter_rows(filter_dict):
            candidate = np.array(vector, dtype=np.float32)
            candidate_norm = np.linalg.norm(candidate)
            score = 0.0 if candidate_norm == 0 else float(np.dot(query, candidate) / (query_norm * candidate_norm))
            scored.append({
                "id": vector_id,
                "text": text,
                "metadata": metadata,
                "score": score,
            })

        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:top_k]

    def delete(self, ids: List[str]):
        if not self.conn:
            raise ValueError("SQLiteVectorDB 未连接")
        self.conn.executemany(
            "DELETE FROM vectors WHERE collection_name = ? AND id = ?",
            [(self.collection_name, vector_id) for vector_id in ids],
        )
        self.conn.commit()
        logger.info(f"删除 {len(ids)} 个 SQLiteVectorDB 向量")

    def clear(self):
        if not self.conn:
            raise ValueError("SQLiteVectorDB 未连接")
        self.conn.execute("DELETE FROM vectors WHERE collection_name = ?", (self.collection_name,))
        self.conn.commit()
        logger.info("SQLiteVectorDB 已清空")

    def get_collection_info(self) -> Dict[str, Any]:
        if not self.conn:
            raise ValueError("SQLiteVectorDB 未连接")
        row = self.conn.execute(
            "SELECT COUNT(*) AS count FROM vectors WHERE collection_name = ?",
            (self.collection_name,),
        ).fetchone()
        return {
            "name": self.collection_name,
            "dimension": self.dimension,
            "count": int(row["count"] if row else 0),
            "path": self.path,
            "status": "active",
        }

    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None


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
        metadata = self.collection.metadata or {}
        return {
            "name": self.collection.name,
            "dimension": metadata.get("dimension"),
            "count": count,
            "metadata": metadata
        }

    def clear(self):
        """清空集合"""
        all_docs = self.collection.get()
        if all_docs and all_docs.get('ids'):
            self.delete(all_docs['ids'])

    def close(self):
        """关闭连接（ChromaDB 不需要显式关闭）"""
        pass


class QdrantAdapter(BaseVectorDB):
    """Qdrant 适配器 - 高性能，适合生产环境"""

    def __init__(self, host: str = "localhost", port: int = 6333, collection_name: str = "documents"):
        self.host = host
        self.port = port
        self.collection_name = collection_name
        self.dimension = None
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

        self.collection_name = name
        self.dimension = dimension

        try:
            exists = self.client.collection_exists(name)
        except Exception:
            try:
                self.client.get_collection(name)
                exists = True
            except Exception:
                exists = False

        if exists:
            logger.info(f"Qdrant 集合已存在: {name}")
            return

        self.client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=dimension, distance=Distance.COSINE)
        )
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
            ids = [str(uuid.uuid4()) for _ in range(len(vectors))]

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
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        search_filter = None
        if filter_dict:
            if any(key in filter_dict for key in ("must", "should", "must_not")):
                search_filter = Filter(**filter_dict)
            else:
                search_filter = Filter(
                    must=[
                        FieldCondition(key=key, match=MatchValue(value=value))
                        for key, value in filter_dict.items()
                    ]
                )

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
            "dimension": self.dimension,
            "vectors_count": info.vectors_count,
            "status": info.status
        }

    def clear(self):
        """清空集合"""
        if self.dimension is None:
            info = self.client.get_collection(self.collection_name)
            self.dimension = info.config.params.vectors.size

        self.client.delete_collection(self.collection_name)
        self.create_collection(self.collection_name, self.dimension)

    def close(self):
        """关闭连接"""
        if self.client:
            self.client.close()


class VectorDBFactory:
    """向量数据库工厂"""

    _adapters = {
        'memory': MemoryVectorDBAdapter,
        'sqlite': SQLiteVectorDBAdapter,
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
