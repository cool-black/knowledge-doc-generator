"""
检索器基类和通用模型
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import AsyncGenerator, List, Optional


class SourceType(Enum):
    """内容来源类型"""
    WEB_PAGE = "web_page"
    ARXIV_PAPER = "arxiv_paper"
    GITHUB_REPO = "github_repo"
    GITHUB_README = "github_readme"
    OFFICIAL_DOC = "official_doc"


@dataclass
class RetrievedContent:
    """检索到的内容"""
    title: str
    url: str
    source_type: SourceType
    content: str = ""  # 原始内容或摘要
    summary: str = ""  # LLM 生成的摘要
    author: str = ""
    publish_date: Optional[datetime] = None
    authority_score: float = 0.5  # 权威性评分 0-1
    relevance_score: float = 0.0  # 相关性评分
    metadata: dict = field(default_factory=dict)

    def __repr__(self) -> str:
        return f"[{self.source_type.value}] {self.title[:50]}... ({self.url[:60]})"


class BaseRetriever(ABC):
    """检索器基类"""

    def __init__(self, config: dict):
        self.config = config
        self.enabled = config.get("enabled", True)

    @abstractmethod
    async def search(
        self,
        query: str,
        max_results: int = 10,
    ) -> List[RetrievedContent]:
        """
        执行搜索
        """
        pass

    def is_available(self) -> bool:
        """检查此检索器是否可用"""
        return self.enabled
