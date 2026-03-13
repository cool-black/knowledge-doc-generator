"""
搜索引擎检索器
支持 Serper、Google Custom Search、Bing Search
"""

import os
from typing import List, Optional

import aiohttp

from .base import BaseRetriever, RetrievedContent, SourceType


class SerperRetriever(BaseRetriever):
    """Serper.dev 搜索引擎"""

    def __init__(self, config: dict):
        super().__init__(config)
        self.api_key = self._get_api_key()
        self.base_url = "https://google.serper.dev/search"

    def _get_api_key(self) -> str:
        api_key = self.config.get("api_key", "")
        if api_key.startswith("${") and api_key.endswith("}"):
            env_var = api_key[2:-1]
            api_key = os.getenv(env_var, "")
        return api_key

    def is_available(self) -> bool:
        return self.enabled and bool(self.api_key)

    async def search(
        self,
        query: str,
        max_results: int = 10,
    ) -> List[RetrievedContent]:
        headers = {
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json",
        }

        payload = {
            "q": query,
            "num": max_results,
            "gl": "us",
            "hl": "zh-cn",
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.base_url, headers=headers, json=payload
            ) as response:
                if response.status != 200:
                    raise Exception(f"Serper API error: {response.status}")

                data = await response.json()

        results = []

        # 处理普通搜索结果
        for item in data.get("organic", [])[:max_results]:
            content = RetrievedContent(
                title=item.get("title", ""),
                url=item.get("link", ""),
                source_type=SourceType.WEB_PAGE,
                content=item.get("snippet", ""),
                metadata={
                    "position": item.get("position"),
                    "source": "serper",
                },
            )
            results.append(content)

        return results


class SearchEngineRetriever:
    """搜索引擎检索器统一接口"""

    def __init__(self, config: dict):
        self.config = config
        self.provider = config.get("provider", "serper")
        self._retriever = self._create_retriever()

    def _create_retriever(self) -> Optional[BaseRetriever]:
        """创建具体的检索器"""
        if self.provider == "serper":
            return SerperRetriever(self.config)
        # TODO: 添加 Google、Bing 支持
        return None

    def is_available(self) -> bool:
        """检查检索器是否可用"""
        return self._retriever is not None and self._retriever.is_available()

    async def search(
        self,
        query: str,
        max_results: Optional[int] = None,
    ) -> List[RetrievedContent]:
        """执行搜索"""
        if not self._retriever or not self._retriever.is_available():
            return []

        max_results = max_results or self.config.get("max_results", 10)
        return await self._retriever.search(query, max_results)
