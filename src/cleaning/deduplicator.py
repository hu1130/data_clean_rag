"""
去重模块
支持精确去重、MinHash 去重和语义去重
"""

import hashlib
from typing import List, Set, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class ExactDeduplicator:
    """精确去重"""

    def __init__(self):
        self.seen_hashes: Set[str] = set()

    def deduplicate(self, texts: List[str]) -> List[str]:
        """精确去重"""
        unique_texts = []
        for text in texts:
            text_hash = hashlib.md5(text.encode()).hexdigest()
            if text_hash not in self.seen_hashes:
                self.seen_hashes.add(text_hash)
                unique_texts.append(text)
        return unique_texts

    def reset(self):
        """重置去重状态"""
        self.seen_hashes.clear()


class MinHashDeduplicator:
    """MinHash 近似去重"""

    def __init__(self, threshold: float = 0.85, num_perm: int = 128):
        try:
            from datasketch import MinHashLSH
        except ImportError:
            raise ImportError("使用 MinHash 去重需要安装 datasketch: pip install datasketch")

        self.threshold = threshold
        self.num_perm = num_perm
        self.lsh = MinHashLSH(threshold=threshold, num_perm=num_perm)
        self.minhash_cls = self._load_minhash_cls()
        self.minhash_lsh_cls = MinHashLSH
        self.minhashes: Dict[str, Any] = {}
        self.counter = 0

    def _load_minhash_cls(self):
        from datasketch import MinHash
        return MinHash

    def _get_shingles(self, text: str, k: int = 5) -> List[str]:
        """获取 k-gram shingles"""
        return [text[i:i+k] for i in range(len(text) - k + 1)]

    def deduplicate(self, texts: List[str]) -> List[str]:
        """MinHash 去重"""
        unique_texts = []

        for text in texts:
            m = self.minhash_cls(num_perm=self.num_perm)
            shingles = self._get_shingles(text)

            for s in shingles:
                m.update(s.encode('utf8'))

            # 查询相似文档
            result = self.lsh.query(m)

            if not result:
                # 没有相似文档，加入 LSH
                doc_id = f"doc_{self.counter}"
                self.lsh.insert(doc_id, m)
                self.minhashes[doc_id] = m
                self.counter += 1
                unique_texts.append(text)
            else:
                logger.info(f"发现重复文档，与 {len(result)} 个文档相似")

        return unique_texts

    def reset(self):
        """重置去重器"""
        self.lsh = self.minhash_lsh_cls(threshold=self.threshold, num_perm=self.num_perm)
        self.minhashes = {}
        self.counter = 0


class DedupPipeline:
    """去重流水线"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.method = self.config.get('method', 'exact')
        self.threshold = self.config.get('threshold', 0.85)

        if self.method == 'exact':
            self.dedup = ExactDeduplicator()
        elif self.method == 'minhash':
            self.dedup = MinHashDeduplicator(threshold=self.threshold)
        else:
            raise ValueError(f"不支持的去重方法: {self.method}")

    def process(self, texts: List[str]) -> List[str]:
        """执行去重"""
        logger.info(f"使用 {self.method} 方法去重，原始数量: {len(texts)}")
        result = self.dedup.deduplicate(texts)
        logger.info(f"去重后数量: {len(result)}")
        return result

    def reset(self):
        """重置去重状态"""
        if hasattr(self.dedup, 'reset'):
            self.dedup.reset()
