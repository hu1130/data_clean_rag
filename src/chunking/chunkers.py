"""
文本分块模块
支持递归分块、固定大小分块和语义分块
"""

from typing import List, Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


def _validate_chunk_params(chunk_size: int, chunk_overlap: int):
    """Validate chunking parameters before any loop starts."""
    if chunk_size <= 0:
        raise ValueError("chunk_size 必须大于 0")
    if chunk_overlap < 0:
        raise ValueError("chunk_overlap 不能小于 0")
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap 必须小于 chunk_size")


def _batch_chunks(chunker, texts: List[str]) -> List[Dict[str, Any]]:
    """批量分块，返回带元数据的结果"""
    results = []
    for i, text in enumerate(texts):
        chunks = chunker.chunk(text)
        for j, chunk in enumerate(chunks):
            results.append({
                'text': chunk,
                'metadata': {
                    'source_doc_id': i,
                    'chunk_index': j,
                    'total_chunks': len(chunks)
                }
            })
    return results


class RecursiveChunker:
    """递归分块器 - 优先在段落、句子边界处分割"""

    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 128):
        _validate_chunk_params(chunk_size, chunk_overlap)
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        # 分隔符按优先级排列：段落 > 换行 > 句子 > 分号 > 逗号 > 空格 > 任意字符
        self.separators = ["\n\n", "\n", "。", "；", "，", " ", ""]

    def chunk(self, text: str) -> List[str]:
        """递归分块"""
        if len(text) <= self.chunk_size:
            return [text] if text.strip() else []

        chunks = []
        start = 0

        while start < len(text):
            end = min(start + self.chunk_size, len(text))

            # 尝试在分隔符处分割
            if end < len(text):
                for sep in self.separators:
                    pos = text.rfind(sep, start, end)
                    candidate_end = pos + len(sep)
                    if pos > start and candidate_end > start + self.chunk_overlap:
                        end = candidate_end
                        break

            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)

            # 计算下一个起始位置（考虑重叠）
            start = end - self.chunk_overlap if end < len(text) else end

        return chunks

    def chunk_batch(self, texts: List[str]) -> List[Dict[str, Any]]:
        """批量分块，返回带元数据的结果"""
        return _batch_chunks(self, texts)


class FixedSizeChunker:
    """固定大小分块器"""

    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 128):
        _validate_chunk_params(chunk_size, chunk_overlap)
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk(self, text: str) -> List[str]:
        """固定大小分块"""
        if len(text) <= self.chunk_size:
            return [text] if text.strip() else []

        chunks = []
        start = 0

        while start < len(text):
            end = min(start + self.chunk_size, len(text))
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            start = end - self.chunk_overlap if end < len(text) else end

        return chunks

    def chunk_batch(self, texts: List[str]) -> List[Dict[str, Any]]:
        """批量分块，返回带元数据的结果"""
        return _batch_chunks(self, texts)


class ChunkingPipeline:
    """分块流水线"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.enabled = self.config.get('enabled', True)
        self.chunk_size = self.config.get('chunk_size', 512)
        self.chunk_overlap = self.config.get('chunk_overlap', 128)
        self.method = self.config.get('method', 'recursive')

        if self.method == 'recursive':
            self.chunker = RecursiveChunker(self.chunk_size, self.chunk_overlap)
        elif self.method == 'fixed':
            self.chunker = FixedSizeChunker(self.chunk_size, self.chunk_overlap)
        else:
            raise ValueError(f"不支持的分块方法: {self.method}")

    def process(self, texts: List[str]) -> List[Dict[str, Any]]:
        """执行分块"""
        if not self.enabled:
            return [
                {
                    'text': text,
                    'metadata': {
                        'source_doc_id': i,
                        'chunk_index': 0,
                        'total_chunks': 1
                    }
                }
                for i, text in enumerate(texts)
                if text and text.strip()
            ]

        logger.info(f"使用 {self.method} 方法分块，chunk_size={self.chunk_size}")
        return self.chunker.chunk_batch(texts)
