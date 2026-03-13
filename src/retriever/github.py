"""
GitHub 检索器
搜索高星仓库、README 内容
"""

import os
from datetime import datetime
from typing import List, Optional

import aiohttp

from .base import BaseRetriever, RetrievedContent, SourceType


class GitHubRetriever(BaseRetriever):
    """GitHub 仓库检索器"""

    def __init__(self, config: dict):
        super().__init__(config)
        self.api_key = self._get_api_key()
        self.min_stars = config.get("min_stars", 100)
        self.max_results = config.get("max_results", 10)
        self.base_url = "https://api.github.com"

    def _get_api_key(self) -> str:
        api_key = self.config.get("api_key", "")
        if api_key.startswith("${") and api_key.endswith("}"):
            env_var = api_key[2:-1]
            api_key = os.getenv(env_var, "")
        # 忽略占位符值
        if api_key in ("", "your_github_token", "xxx", "placeholder"):
            return ""
        return api_key

    def is_available(self) -> bool:
        return self.enabled

    def _get_headers(self) -> dict:
        headers = {
            "Accept": "application/vnd.github.v3+json",
        }
        if self.api_key:
            headers["Authorization"] = f"token {self.api_key}"
        return headers

    async def search(
        self,
        query: str,
        max_results: Optional[int] = None,
    ) -> List[RetrievedContent]:
        """搜索 GitHub 仓库"""
        max_results = max_results or self.max_results

        # 构建搜索查询
        search_query = f"{query} stars:>{self.min_stars}"

        url = f"{self.base_url}/search/repositories"
        params = {
            "q": search_query,
            "sort": "stars",
            "order": "desc",
            "per_page": max_results,
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, headers=self._get_headers(), params=params
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"GitHub API error: {response.status} - {error_text}")

                data = await response.json()

        results = []
        for repo in data.get("items", []):
            # 获取 README 内容
            readme_content = await self._fetch_readme(session, repo["full_name"])

            content = f"""
Repository: {repo['full_name']}
Description: {repo['description'] or 'No description'}
Stars: {repo['stargazers_count']}
Language: {repo['language'] or 'Unknown'}
Topics: {', '.join(repo.get('topics', []))}

README:
{readme_content[:3000]}...
"""

            result = RetrievedContent(
                title=repo["full_name"],
                url=repo["html_url"],
                source_type=SourceType.GITHUB_REPO,
                content=content,
                author=repo["owner"]["login"],
                publish_date=datetime.fromisoformat(
                    repo["created_at"].replace("Z", "+00:00")
                ),
                authority_score=min(0.5 + repo["stargazers_count"] / 10000, 0.95),
                metadata={
                    "stars": repo["stargazers_count"],
                    "forks": repo["forks_count"],
                    "language": repo["language"],
                    "topics": repo.get("topics", []),
                    "updated_at": repo["updated_at"],
                    "source": "github",
                },
            )
            results.append(result)

        return results

    async def _fetch_readme(
        self, session: aiohttp.ClientSession, repo_full_name: str
    ) -> str:
        """获取仓库 README 内容"""
        url = f"{self.base_url}/repos/{repo_full_name}/readme"

        try:
            async with session.get(url, headers=self._get_headers()) as response:
                if response.status != 200:
                    return "README not available"

                data = await response.json()
                import base64

                content = base64.b64decode(data["content"]).decode("utf-8", errors="ignore")
                return content
        except Exception:
            return "README fetch failed"
