"""Embedding backends for local, OpenAI, and sentence-transformers models."""

import hashlib
import logging
import os
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


class HashEmbeddingBackend:
    """Lightweight deterministic embedding backend for development and tests."""

    def __init__(self, dimension: int = 384):
        self._dimension = dimension

    def encode(
        self,
        texts: List[str],
        batch_size: int = 32,
        normalize_embeddings: bool = True,
        show_progress_bar: bool = False,
    ) -> np.ndarray:
        vectors = [self._encode_one(text, normalize_embeddings) for text in texts]
        return np.array(vectors, dtype=np.float32)

    def _encode_one(self, text: str, normalize: bool) -> np.ndarray:
        vector = np.zeros(self._dimension, dtype=np.float32)
        tokens = text.split() or list(text)

        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            value = int.from_bytes(digest, byteorder="little", signed=False)
            index = value % self._dimension
            sign = 1.0 if value & 1 else -1.0
            vector[index] += sign

        if normalize:
            norm = np.linalg.norm(vector)
            if norm > 0:
                vector = vector / norm

        return vector

    def get_sentence_embedding_dimension(self) -> int:
        return self._dimension


class OpenAIEmbedding:
    """OpenAI embedding backend."""

    def __init__(
        self,
        model_name: str = "text-embedding-3-small",
        api_key: Optional[str] = None,
        dimension: Optional[int] = None,
    ):
        self.model_name = model_name
        self.api_key = api_key
        self.configured_dimension = dimension
        self._client = None

    @property
    def client(self):
        if not self.api_key:
            raise ValueError("OpenAI embedding requires an API key. Set OPENAI_API_KEY or embedding.api_key.")

        if self._client is None:
            try:
                import openai
            except ImportError:
                raise ImportError("Please install openai to use OpenAI embeddings: pip install openai")
            self._client = openai.OpenAI(api_key=self.api_key)
        return self._client

    def encode(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []

        batch_size = 100
        all_embeddings = []
        for index in range(0, len(texts), batch_size):
            batch = texts[index:index + batch_size]
            kwargs = {"dimensions": self.configured_dimension} if self.configured_dimension else {}
            response = self.client.embeddings.create(
                model=self.model_name,
                input=batch,
                **kwargs,
            )
            all_embeddings.extend(item.embedding for item in response.data)

        return all_embeddings

    @property
    def dimension(self) -> int:
        if self.configured_dimension:
            return self.configured_dimension

        dims = {
            "text-embedding-3-small": 1536,
            "text-embedding-3-large": 3072,
            "text-embedding-ada-002": 1536,
        }
        return dims.get(self.model_name, 1536)


class EmbeddingModel:
    """Unified embedding model wrapper."""

    def __init__(
        self,
        model_name: str = "BAAI/bge-large-zh-v1.5",
        device: str = "auto",
        batch_size: int = 32,
        normalize_embeddings: bool = True,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        api_key_env: str = "OPENAI_API_KEY",
        dimension: Optional[int] = None,
    ):
        self.model_name = model_name
        self.device = device
        self.batch_size = batch_size
        self.normalize_embeddings = normalize_embeddings
        self.provider = (provider or self._infer_provider(model_name)).lower()
        self.api_key = api_key
        self.api_key_env = api_key_env
        self.configured_dimension = dimension
        self.model = None
        self._load_model()

    def _infer_provider(self, model_name: str) -> str:
        model_key = model_name.lower()
        if model_key in {"hash", "hashing", "local-hash"}:
            return "hash"
        if model_key.startswith("openai/") or model_key.startswith("text-embedding-"):
            return "openai"
        return "sentence_transformers"

    def _load_model(self):
        if self.provider in {"hash", "hashing", "local-hash"}:
            self.model = HashEmbeddingBackend(dimension=self.configured_dimension or 384)
            logger.info("Using HashEmbeddingBackend for development/testing.")
            return

        if self.provider == "openai":
            model_name = self.model_name.removeprefix("openai/")
            self.model = OpenAIEmbedding(
                model_name=model_name,
                api_key=self.api_key or os.environ.get(self.api_key_env),
                dimension=self.configured_dimension,
            )
            logger.info("Using OpenAI embedding model: %s", model_name)
            return

        if self.provider not in {"sentence_transformers", "sentence-transformers", "local"}:
            raise ValueError(f"Unsupported embedding provider: {self.provider}")

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise ImportError("Please install sentence-transformers: pip install sentence-transformers")

        device = None if self.device == "auto" else self.device
        self.model = SentenceTransformer(self.model_name, device=device)
        logger.info("Loaded sentence-transformers model: %s", self.model_name)

    def encode(self, texts: List[str], normalize: Optional[bool] = None) -> np.ndarray:
        if not texts:
            return np.array([])

        valid_texts = [text for text in texts if text and isinstance(text, str)]
        if not valid_texts:
            return np.array([])

        normalize = self.normalize_embeddings if normalize is None else normalize

        if isinstance(self.model, OpenAIEmbedding):
            embeddings = np.array(self.model.encode(valid_texts), dtype=np.float32)
            if normalize:
                embeddings = self._normalize_array(embeddings)
            return embeddings

        return self.model.encode(
            valid_texts,
            batch_size=self.batch_size,
            normalize_embeddings=normalize,
            show_progress_bar=True,
        )

    def encode_single(self, text: str, normalize: Optional[bool] = None) -> np.ndarray:
        return self.encode([text], normalize=normalize)[0]

    def _normalize_array(self, embeddings: np.ndarray) -> np.ndarray:
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1
        return embeddings / norms

    @property
    def dimension(self) -> int:
        if isinstance(self.model, OpenAIEmbedding):
            return self.model.dimension
        return self.model.get_sentence_embedding_dimension()

    def info(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "model_name": self.model_name,
            "dimension": self.dimension,
            "batch_size": self.batch_size,
            "normalize_embeddings": self.normalize_embeddings,
        }
