"""
arXiv 论文检索器
"""

import asyncio
from datetime import datetime
from typing import List, Optional

import arxiv

from .base import BaseRetriever, RetrievedContent, SourceType


class ArxivRetriever(BaseRetriever):
    """arXiv 学术论文检索器"""

    def __init__(self, config: dict):
        super().__init__(config)
        self.client = arxiv.Client()
        self.max_results = config.get("max_results", 10)
        self.sort_by = config.get("sort_by", "submittedDate")

    def is_available(self) -> bool:
        return self.enabled

    async def search(
        self,
        query: str,
        max_results: Optional[int] = None,
    ) -> List[RetrievedContent]:
        """搜索 arXiv 论文"""
        max_results = max_results or self.max_results

        # 构建搜索
        search = arxiv.Search(
            query=query,
            max_results=max_results,
            sort_by=getattr(arxiv.SortCriterion, self.sort_by, arxiv.SortCriterion.SubmittedDate),
        )

        def _fetch_results():
            return list(self.client.results(search))

        loop = asyncio.get_event_loop()
        papers = await loop.run_in_executor(None, _fetch_results)

        results = []
        for paper in papers:
            # 获取 PDF 内容（可选）
            content = f"""
Title: {paper.title}
Abstract: {paper.summary}
Authors: {', '.join(str(a) for a in paper.authors)}
Categories: {', '.join(paper.categories)}
"""

            result = RetrievedContent(
                title=paper.title,
                url=paper.pdf_url or paper.entry_id,
                source_type=SourceType.ARXIV_PAPER,
                content=content,
                author=", ".join(str(a) for a in paper.authors[:3]),
                publish_date=paper.published,
                authority_score=0.9,  # 学术论文权威性较高
                metadata={
                    "arxiv_id": paper.get_short_id(),
                    "primary_category": paper.primary_category,
                    "categories": paper.categories,
                    "doi": paper.doi,
                    "journal_ref": paper.journal_ref,
                    "source": "arxiv",
                },
            )
            results.append(result)

        return results
