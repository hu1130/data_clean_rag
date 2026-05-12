"""
嵌入模型模块
支持多种嵌入模型，包括 BGE、OpenAI 等
"""

from typing import List, Optional, Dict, Any
import numpy as np
import logging

logger = logging.getLogger(__name__)


class EmbeddingModel:
    """嵌入模型封装"""

    def __init__(self, model_name: str = "BAAI/bge-large-zh-v1.5", device: str = "auto", batch_size: int = 32):
        self.model_name = model_name
        self.device = device
        self.batch_size = batch_size
        self.model = None
        self.tokenizer = None
        self._load_model()

    def _load_model(self):
        """加载模型"""
        try:
            from sentence_transformers import SentenceTransformer

            self.model = SentenceTransformer(self.model_name, device=self.device)
            logger.info(f"模型加载成功: {self.model_name}")
        except ImportError:
            raise ImportError("请安装 sentence-transformers: pip install sentence-transformers")

    def encode(self, texts: List[str], normalize: bool = True) -> np.ndarray:
        """
        编码文本为向量

        Args:
            texts: 文本列表
            normalize: 是否归一化向量

        Returns:
            向量数组
        """
        if not texts:
            return np.array([])

        # 过滤空文本
        valid_texts = [t for t in texts if t and isinstance(t, str)]

        embeddings = self.model.encode(
            valid_texts,
            batch_size=self.batch_size,
            normalize_embeddings=normalize,
            show_progress_bar=True
        )

        return embeddings

    def encode_single(self, text: str, normalize: bool = True) -> np.ndarray:
        """编码单个文本"""
        return self.encode([text], normalize=normalize)[0]

    @property
    def dimension(self) -> int:
        """获取向量维度"""
        return self.model.get_sentence_embedding_dimension()


class OpenAIEmbedding:
    """OpenAI 嵌入模型"""

    def __init__(self, model_name: str = "text-embedding-3-small", api_key: Optional[str] = None):
        self.model_name = model_name
        self.api_key = api_key
        self._client = None

    @property
    def client(self):
        """延迟初始化客户端"""
        if self._client is None:
            try:
                import openai
                self._client = openai.OpenAI(api_key=self.api_key)
            except ImportError:
                raise ImportError("请安装 openai: pip install openai")
        return self._client

    def encode(self, texts: List[str]) -> List[List[float]]:
        """编码文本"""
        if not texts:
            return []

        # OpenAI API 限制 batch size
        batch_size = 100
        all_embeddings = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i+batch_size]
            response = self.client.embeddings.create(
                model=self.model_name,
                input=batch
            )
            embeddings = [item.embedding for item in response.data]
            all_embeddings.extend(embeddings)

        return all_embeddings

    @property
    def dimension(self) -> int:
        """获取维度"""
        dims = {
            "text-embedding-3-small": 1536,
            "text-embedding-3-large": 3072,
            "text-embedding-ada-002": 1536
        }
        return dims.get(self.model_name, 1536)
