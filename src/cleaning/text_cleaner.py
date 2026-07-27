"""
Text cleaning and explainable quality filtering.
"""

import html
import logging
import re
from collections import Counter
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class TextCleaner:
    """Text cleaner."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self._compile_patterns()

    def _compile_patterns(self):
        """Compile regex patterns once."""
        self.patterns = {
            'html_tags': re.compile(r'<[^>]+>'),
            'urls': re.compile(r'https?://\S+|www\.\S+'),
            'emails': re.compile(r'\S+@\S+\.\S+'),
            'extra_whitespace': re.compile(r'\s+'),
            'special_chars': re.compile(r'[^\w\s\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]'),
        }

    def clean(self, text: str, rules: Optional[Dict[str, bool]] = None) -> str:
        """Clean one text item."""
        if not text or not isinstance(text, str):
            return ""

        rules = rules or self.config.get('text_cleaning', {})

        if rules.get('remove_html', True):
            text = html.unescape(text)
            text = self.patterns['html_tags'].sub('', text)

        if rules.get('remove_urls', True):
            text = self.patterns['urls'].sub('', text)

        if rules.get('remove_emails', True):
            text = self.patterns['emails'].sub('', text)

        if rules.get('normalize_whitespace', True):
            text = self.patterns['extra_whitespace'].sub(' ', text)

        if rules.get('lowercase', False):
            text = text.lower()

        if rules.get('remove_punctuation', False):
            text = self.patterns['special_chars'].sub('', text)

        text = text.strip()

        min_len = rules.get('min_length', 0)
        max_len = rules.get('max_length', float('inf'))

        if len(text) < min_len:
            logger.warning("Text length %s is less than min_length %s", len(text), min_len)
            return ""

        if len(text) > max_len:
            text = text[:max_len]
            logger.warning("Text truncated to max_length %s", max_len)

        return text

    def batch_clean(self, texts: List[str], rules: Optional[Dict[str, bool]] = None) -> List[str]:
        """Clean a batch of texts."""
        return [self.clean(text, rules) for text in texts if text]


class QualityScorer:
    """Rule-based quality scorer with explainable rejection reasons."""

    MOJIBAKE_MARKERS = (
        "\ufffd",
        "Ã",
        "Â",
        "â€",
        "æ",
        "ç",
        "å",
    )

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.enabled = self.config.get('enabled', True)
        self.min_word_count = self.config.get('min_word_count', 5)
        self.max_word_count = self.config.get('max_word_count', 1000)
        self.min_score = self.config.get('min_score', 60)
        self.remove_gibberish = self.config.get('remove_gibberish', True)

        self.max_symbol_ratio = self.config.get('max_symbol_ratio', 0.35)
        self.max_digit_ratio = self.config.get('max_digit_ratio', 0.80)
        self.max_repeated_char_ratio = self.config.get('max_repeated_char_ratio', 0.30)
        self.max_repeated_line_ratio = self.config.get('max_repeated_line_ratio', 0.50)
        self.min_printable_ratio = self.config.get('min_printable_ratio', 0.90)
        self.max_mojibake_ratio = self.config.get('max_mojibake_ratio', 0.02)
        self.max_ocr_noise_ratio = self.config.get('max_ocr_noise_ratio', 0.45)
        self.max_html_tag_count = self.config.get('max_html_tag_count', 0)

    def score(self, text: str) -> Dict[str, Any]:
        """Return valid flag, score, reasons, and measurable quality metrics."""
        if not text or not isinstance(text, str):
            return {
                'valid': False,
                'score': 0,
                'reasons': ['empty_text'],
                'metrics': self._empty_metrics(),
            }

        metrics = self._measure(text)
        if not self.enabled:
            return {
                'valid': True,
                'score': 100,
                'reasons': [],
                'metrics': metrics,
            }

        reasons = []
        score = 100
        word_count = metrics['word_count']

        if word_count < self.min_word_count:
            reasons.append('too_short')
            score -= 40

        if word_count > self.max_word_count:
            reasons.append('too_long')
            score -= 35

        if self.remove_gibberish and metrics['printable_ratio'] < self.min_printable_ratio:
            reasons.append('non_printable_chars')
            score -= 30

        if self.remove_gibberish and metrics['mojibake_ratio'] > self.max_mojibake_ratio:
            reasons.append('mojibake')
            score -= 35

        if metrics['symbol_ratio'] > self.max_symbol_ratio:
            reasons.append('too_many_symbols')
            score -= 25

        if metrics['digit_ratio'] > self.max_digit_ratio:
            reasons.append('too_many_digits')
            score -= 15

        if metrics['repeated_char_ratio'] > self.max_repeated_char_ratio:
            reasons.append('repeated_characters')
            score -= 25

        if metrics['repeated_line_ratio'] > self.max_repeated_line_ratio:
            reasons.append('repeated_lines')
            score -= 25

        if metrics['ocr_noise_ratio'] > self.max_ocr_noise_ratio:
            reasons.append('ocr_noise')
            score -= 20

        if metrics['html_tag_count'] > self.max_html_tag_count:
            reasons.append('html_residue')
            score -= 15

        score = max(0, min(100, score))
        blocking_reasons = {
            'too_short',
            'too_long',
            'non_printable_chars',
            'mojibake',
            'repeated_characters',
            'repeated_lines',
            'ocr_noise',
        }
        valid = (
            word_count >= self.min_word_count
            and word_count <= self.max_word_count
            and score >= self.min_score
            and not (set(reasons) & blocking_reasons)
        )

        return {
            'valid': valid,
            'score': score,
            'reasons': reasons,
            'metrics': metrics,
        }

    def _empty_metrics(self) -> Dict[str, Any]:
        return {
            'char_count': 0,
            'word_count': 0,
            'line_count': 0,
            'symbol_ratio': 0.0,
            'digit_ratio': 0.0,
            'printable_ratio': 0.0,
            'repeated_char_ratio': 0.0,
            'repeated_line_ratio': 0.0,
            'mojibake_ratio': 0.0,
            'ocr_noise_ratio': 0.0,
            'html_tag_count': 0,
        }

    def _measure(self, text: str) -> Dict[str, Any]:
        char_count = len(text)
        lines = text.splitlines() or [text]
        non_empty_lines = [line.strip() for line in lines if line.strip()]
        printable_count = sum(1 for char in text if char.isprintable())
        symbol_count = sum(1 for char in text if self._is_symbol(char))
        digit_count = sum(1 for char in text if char.isdigit())
        mojibake_count = self._count_mojibake_markers(text)

        return {
            'char_count': char_count,
            'word_count': self._count_words(text),
            'line_count': len(lines),
            'symbol_ratio': round(symbol_count / char_count, 4),
            'digit_ratio': round(digit_count / char_count, 4),
            'printable_ratio': round(printable_count / char_count, 4),
            'repeated_char_ratio': round(self._longest_char_run(text) / char_count, 4),
            'repeated_line_ratio': round(self._repeated_line_ratio(non_empty_lines), 4),
            'mojibake_ratio': round(mojibake_count / char_count, 4),
            'ocr_noise_ratio': round(self._ocr_noise_ratio(text), 4),
            'html_tag_count': len(re.findall(r'<[A-Za-z][^>]*>', text)),
        }

    def _count_words(self, text: str) -> int:
        """Estimate length for CJK and whitespace-tokenized languages."""
        cjk_chars = re.findall(r'[\u4e00-\u9fff]', text)
        non_cjk_text = re.sub(r'[\u4e00-\u9fff]', ' ', text)
        word_tokens = re.findall(r'\b\w+\b', non_cjk_text)

        if cjk_chars:
            return len(cjk_chars) + len(word_tokens)

        return len(word_tokens)

    def _is_symbol(self, char: str) -> bool:
        if char.isspace() or char.isalnum():
            return False
        return not re.match(r'[\u4e00-\u9fff]', char)

    def _longest_char_run(self, text: str) -> int:
        longest = 1
        current = 1
        previous = text[0]
        for char in text[1:]:
            if char == previous and not char.isspace():
                current += 1
            else:
                longest = max(longest, current)
                current = 1
                previous = char
        return max(longest, current)

    def _repeated_line_ratio(self, lines: List[str]) -> float:
        if len(lines) < 3:
            return 0.0

        counts = Counter(lines)
        repeated = sum(count - 1 for count in counts.values() if count > 1)
        return repeated / len(lines)

    def _count_mojibake_markers(self, text: str) -> int:
        return sum(text.count(marker) for marker in self.MOJIBAKE_MARKERS)

    def _ocr_noise_ratio(self, text: str) -> float:
        tokens = re.findall(r'\b\w+\b', text)
        if len(tokens) < 20:
            return 0.0

        single_char_tokens = sum(1 for token in tokens if len(token) == 1)
        return single_char_tokens / len(tokens)

    def _is_gibberish(self, text: str) -> bool:
        result = self.score(text)
        reasons = set(result['reasons'])
        return bool({'non_printable_chars', 'mojibake', 'repeated_characters'} & reasons)


class QualityFilter:
    """Compatibility wrapper around QualityScorer."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.scorer = QualityScorer(config)
        self.config = self.scorer.config
        self.enabled = self.scorer.enabled
        self.min_word_count = self.scorer.min_word_count
        self.max_word_count = self.scorer.max_word_count
        self.languages = self.config.get('language_filter', [])

    def score(self, text: str) -> Dict[str, Any]:
        return self.scorer.score(text)

    def is_valid(self, text: str) -> bool:
        return self.score(text)['valid']

    def _count_words(self, text: str) -> int:
        return self.scorer._count_words(text)

    def _is_gibberish(self, text: str) -> bool:
        return self.scorer._is_gibberish(text)

    def filter_batch(self, texts: List[str]) -> List[str]:
        return [text for text in texts if self.is_valid(text)]
