"""
内容筛选和去重模块
"""

import hashlib
from dataclasses import dataclass
from typing import List

import numpy as np

from ..retriever.base import RetrievedContent


@dataclass
class FilterResult:
    """筛选结果"""
    content: RetrievedContent
    keep: bool
    reason: str = ""


class ContentFilter:
    """内容筛选器"""

    def __init__(self, config: dict):
        self.config = config
        self.min_authority_score = config.get("min_authority_score", 0.6)
        self.min_content_length = config.get("min_content_length", 500)
        self.max_age_days = config.get("max_age_days", 365)
        self.dedup_threshold = config.get("dedup_threshold", 0.85)

        # 简单的哈希去重
        self._seen_hashes = set()

    def filter_all(self, contents: List[RetrievedContent]) -> List[RetrievedContent]:
        """执行所有筛选步骤"""
        results = []

        for content in contents:
            result = self._filter_single(content)
            if result.keep:
                results.append(content)

        return results

    def _filter_single(self, content: RetrievedContent) -> FilterResult:
        """筛选单个内容"""
        # 1. 权威性检查
        if content.authority_score < self.min_authority_score:
            return FilterResult(
                content=content,
                keep=False,
                reason=f"Authority score {content.authority_score:.2f} < {self.min_authority_score}",
            )

        # 2. 内容长度检查
        if len(content.content) < self.min_content_length:
            return FilterResult(
                content=content,
                keep=False,
                reason=f"Content length {len(content.content)} < {self.min_content_length}",
            )

        # 3. 去重检查（简单版本：URL 和内容哈希）
        url_hash = hashlib.md5(content.url.encode()).hexdigest()
        if url_hash in self._seen_hashes:
            return FilterResult(content=content, keep=False, reason="Duplicate URL")
        self._seen_hashes.add(url_hash)

        # 内容前 500 字的哈希
        content_prefix = content.content[:500].encode()
        content_hash = hashlib.md5(content_prefix).hexdigest()
        if content_hash in self._seen_hashes:
            return FilterResult(content=content, keep=False, reason="Duplicate content")
        self._seen_hashes.add(content_hash)

        return FilterResult(content=content, keep=True)

    def rank_by_relevance(
        self,
        contents: List[RetrievedContent],
        query: str,
    ) -> List[RetrievedContent]:
        """
        按相关性排序（简化版本：基于标题匹配）
        TODO: 使用 embedding 计算语义相似度
        """
        query_words = set(query.lower().split())

        def relevance_score(content: RetrievedContent) -> float:
            title_words = set(content.title.lower().split())
            content_words = set(content.content[:1000].lower().split())

            title_match = len(query_words & title_words) / len(query_words)
            content_match = len(query_words & content_words) / len(query_words)

            # 综合评分
            score = (
                title_match * 0.4 +  # 标题匹配权重高
                content_match * 0.3 +
                content.authority_score * 0.2 +
                (1 if content.source_type.value == "arxiv_paper" else 0) * 0.1
            )
            return score

        return sorted(contents, key=relevance_score, reverse=True)
