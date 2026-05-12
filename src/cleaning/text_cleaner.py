"""
文本清洗模块
提供多种文本清洗功能
"""

import re
import html
from typing import List, Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


class TextCleaner:
    """文本清洗器"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self._compile_patterns()

    def _compile_patterns(self):
        """预编译正则表达式"""
        self.patterns = {
            'html_tags': re.compile(r'<[^>]+>'),
            'urls': re.compile(r'https?://\S+|www\.\S+'),
            'emails': re.compile(r'\S+@\S+\.\S+'),
            'extra_whitespace': re.compile(r'\s+'),
            'special_chars': re.compile(r'[^\w\s\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]'),
        }

    def clean(self, text: str, rules: Optional[Dict[str, bool]] = None) -> str:
        """
        执行文本清洗

        Args:
            text: 原始文本
            rules: 清洗规则配置

        Returns:
            清洗后的文本
        """
        if not text or not isinstance(text, str):
            return ""

        rules = rules or self.config.get('text_cleaning', {})

        # 1. HTML 解码和标签移除
        if rules.get('remove_html', True):
            text = html.unescape(text)
            text = self.patterns['html_tags'].sub('', text)

        # 2. URL 移除
        if rules.get('remove_urls', True):
            text = self.patterns['urls'].sub('', text)

        # 3. 邮箱移除
        if rules.get('remove_emails', True):
            text = self.patterns['emails'].sub('', text)

        # 4. 空白字符规范化
        if rules.get('normalize_whitespace', True):
            text = self.patterns['extra_whitespace'].sub(' ', text)

        # 5. 小写转换
        if rules.get('lowercase', False):
            text = text.lower()

        # 6. 去除首尾空白
        text = text.strip()

        # 7. 长度过滤
        min_len = rules.get('min_length', 0)
        max_len = rules.get('max_length', float('inf'))

        if len(text) < min_len:
            logger.warning(f"文本长度 {len(text)} 小于最小长度 {min_len}")
            return ""

        if len(text) > max_len:
            text = text[:max_len]
            logger.warning(f"文本截断至最大长度 {max_len}")

        return text

    def batch_clean(self, texts: List[str], rules: Optional[Dict[str, bool]] = None) -> List[str]:
        """批量清洗文本"""
        return [self.clean(text, rules) for text in texts if text]


class QualityFilter:
    """质量过滤器"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.min_word_count = self.config.get('min_word_count', 5)
        self.max_word_count = self.config.get('max_word_count', 1000)
        self.languages = self.config.get('language_filter', [])

    def is_valid(self, text: str) -> bool:
        """检查文本是否通过质量过滤"""
        if not text:
            return False

        # 字数检查
        word_count = len(text.split())
        if word_count < self.min_word_count or word_count > self.max_word_count:
            return False

        # 乱码检测（简单实现）
        if self.config.get('remove_gibberish', True):
            if self._is_gibberish(text):
                return False

        return True

    def _is_gibberish(self, text: str) -> bool:
        """检测文本是否为乱码"""
        # 检查可打印字符比例
        printable_ratio = sum(1 for c in text if c.isprintable()) / len(text)
        if printable_ratio < 0.8:
            return True

        # 检查重复字符比例
        unique_chars = len(set(text))
        if unique_chars / len(text) < 0.1 and len(text) > 50:
            return True

        return False

    def filter_batch(self, texts: List[str]) -> List[str]:
        """批量过滤"""
        return [text for text in texts if self.is_valid(text)]
