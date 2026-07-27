"""Optional reranking layer for search results."""

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class BaseReranker:
    """Reranker interface."""

    def rerank(
        self,
        query: str,
        results: List[Dict[str, Any]],
        top_k: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError


class NoopReranker(BaseReranker):
    """Return vector search results unchanged."""

    def rerank(
        self,
        query: str,
        results: List[Dict[str, Any]],
        top_k: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        return results[:top_k] if top_k is not None else results


class KeywordReranker(BaseReranker):
    """Dependency-free lexical reranker for tests and simple deployments."""

    def rerank(
        self,
        query: str,
        results: List[Dict[str, Any]],
        top_k: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        query_terms = self._tokens(query)
        if not query_terms:
            return results[:top_k] if top_k is not None else results

        scored = []
        for index, result in enumerate(results):
            text_terms = self._tokens(result.get("text", ""))
            overlap = len(query_terms & text_terms)
            coverage = overlap / len(query_terms)
            vector_score = float(result.get("score", 0.0))
            rerank_score = coverage + (vector_score * 0.01)

            updated = dict(result)
            updated["vector_score"] = result.get("score", result.get("distance"))
            updated["rerank_score"] = round(rerank_score, 6)
            updated["_original_rank"] = index
            scored.append(updated)

        scored.sort(key=lambda item: (item["rerank_score"], -item["_original_rank"]), reverse=True)
        for item in scored:
            item.pop("_original_rank", None)
        return scored[:top_k] if top_k is not None else scored

    def _tokens(self, text: str) -> set:
        cjk_chars = re.findall(r"[\u4e00-\u9fff]", text)
        latin_tokens = re.findall(r"\b\w+\b", re.sub(r"[\u4e00-\u9fff]", " ", text.lower()))
        return set(cjk_chars + latin_tokens)


class CrossEncoderReranker(BaseReranker):
    """Cross-encoder reranker backed by sentence-transformers."""

    def __init__(self, model_name: str, device: str = "auto", batch_size: int = 32):
        self.model_name = model_name
        self.device = device
        self.batch_size = batch_size
        self.model = self._load_model()

    def _load_model(self):
        try:
            from sentence_transformers import CrossEncoder
        except ImportError:
            raise ImportError("请安装 sentence-transformers 以使用 cross_encoder reranker: pip install sentence-transformers")

        device = None if self.device == "auto" else self.device
        logger.info("加载 CrossEncoder reranker: %s", self.model_name)
        return CrossEncoder(self.model_name, device=device)

    def rerank(
        self,
        query: str,
        results: List[Dict[str, Any]],
        top_k: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        if not results:
            return []

        pairs = [(query, result.get("text", "")) for result in results]
        scores = self.model.predict(pairs, batch_size=self.batch_size)
        scored = []
        for result, score in zip(results, scores):
            updated = dict(result)
            updated["vector_score"] = result.get("score", result.get("distance"))
            updated["rerank_score"] = float(score)
            scored.append(updated)

        scored.sort(key=lambda item: item["rerank_score"], reverse=True)
        return scored[:top_k] if top_k is not None else scored


class RerankerFactory:
    """Create rerankers from config."""

    @classmethod
    def create(cls, config: Optional[Dict[str, Any]] = None) -> BaseReranker:
        config = config or {}
        if not config.get("enabled", False):
            return NoopReranker()

        reranker_type = config.get("type", "cross_encoder").lower()
        if reranker_type in {"none", "noop", "disabled"}:
            return NoopReranker()
        if reranker_type in {"keyword", "lexical"}:
            return KeywordReranker()
        if reranker_type in {"cross_encoder", "cross-encoder", "sentence_transformers"}:
            return CrossEncoderReranker(
                model_name=config.get("model_name", "BAAI/bge-reranker-base"),
                device=config.get("device", "auto"),
                batch_size=config.get("batch_size", 32),
            )

        raise ValueError(f"不支持的 reranker 类型: {reranker_type}")
