"""
可配置的 LLM 客户端
支持 OpenAI、Anthropic、Azure、本地模型等
"""

import asyncio
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncGenerator, Dict, List, Optional, Any

import yaml
from pydantic import BaseModel


async def retry_with_backoff(
    func,
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    exceptions=(Exception,),
):
    """带指数退避的重试机制"""
    delay = initial_delay
    last_exception = None

    for attempt in range(max_retries + 1):
        try:
            return await func()
        except exceptions as e:
            last_exception = e
            if attempt < max_retries:
                # 使用 stderr 避免污染 stdout
                import sys
                sys.stderr.write(f"请求失败，{delay}秒后重试... (尝试 {attempt + 1}/{max_retries})\n")
                await asyncio.sleep(delay)
                delay = min(delay * 2, max_delay)  # 指数退避
            else:
                raise last_exception


@dataclass
class LLMResponse:
    """LLM 响应封装"""
    content: str
    usage: Dict[str, int]  # prompt_tokens, completion_tokens
    model: str


class BaseLLMClient(ABC):
    """LLM 客户端基类"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.model = config.get("model", "")

    @abstractmethod
    async def generate(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        """生成完整响应"""
        pass

    @abstractmethod
    async def stream_generate(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncGenerator[str, None]:
        """流式生成响应"""
        pass


class AnthropicClient(BaseLLMClient):
    """Anthropic Claude 客户端"""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        import anthropic

        self.client = anthropic.AsyncAnthropic(
            api_key=config.get("api_key"),
            base_url=config.get("base_url"),
        )

    async def generate(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        # 分离 system message
        system_msg = None
        chat_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_msg = msg["content"]
            else:
                chat_messages.append(msg)

        response = await self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens or self.config.get("max_tokens", 4096),
            temperature=temperature or self.config.get("temperature", 0.3),
            system=system_msg,
            messages=chat_messages,
        )

        return LLMResponse(
            content=response.content[0].text,
            usage={
                "prompt_tokens": response.usage.input_tokens,
                "completion_tokens": response.usage.output_tokens,
            },
            model=self.model,
        )

    async def stream_generate(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncGenerator[str, None]:
        system_msg = None
        chat_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_msg = msg["content"]
            else:
                chat_messages.append(msg)

        async with self.client.messages.stream(
            model=self.model,
            max_tokens=max_tokens or self.config.get("max_tokens", 4096),
            temperature=temperature or self.config.get("temperature", 0.3),
            system=system_msg,
            messages=chat_messages,
        ) as stream:
            async for text in stream.text_stream:
                yield text


class OpenAIClient(BaseLLMClient):
    """OpenAI / 兼容 OpenAI API 的客户端"""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        import openai
        import httpx

        # 检测并配置代理
        skip_proxy = config.get("skip_proxy", False)
        http_proxy = config.get("http_proxy") or os.getenv("HTTP_PROXY") or os.getenv("http_proxy")
        https_proxy = config.get("https_proxy") or os.getenv("HTTPS_PROXY") or os.getenv("https_proxy")

        # 如果没有显式配置且不跳过代理，尝试从 urllib 获取系统代理
        if not skip_proxy and not http_proxy and not https_proxy:
            import urllib.request
            proxies = urllib.request.getproxies()
            http_proxy = proxies.get("http", "")
            https_proxy = proxies.get("https", "")

        # 获取超时时间配置（默认60秒）
        timeout = config.get("timeout", 60.0)

        # 创建 HTTP 客户端
        if skip_proxy or (not http_proxy and not https_proxy):
            http_client = httpx.AsyncClient(timeout=timeout)
        else:
            # 使用 proxy 参数配置代理
            proxy_config = https_proxy or http_proxy
            http_client = httpx.AsyncClient(proxy=proxy_config, timeout=timeout)

        self.client = openai.AsyncOpenAI(
            api_key=config.get("api_key"),
            base_url=config.get("base_url"),
            http_client=http_client,
        )

    async def generate(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        from openai import RateLimitError

        async def _do_generate():
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature or self.config.get("temperature", 1),
                max_tokens=max_tokens or self.config.get("max_tokens", 4096),
            )
            return response

        response = await retry_with_backoff(
            _do_generate,
            max_retries=3,
            initial_delay=2.0,
            exceptions=(RateLimitError,),
        )

        return LLMResponse(
            content=response.choices[0].message.content,
            usage={
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
            },
            model=self.model,
        )

    async def stream_generate(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncGenerator[str, None]:
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature or self.config.get("temperature", 0.3),
            max_tokens=max_tokens or self.config.get("max_tokens", 4096),
            stream=True,
        )

        async for chunk in response:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content


class LLMClientFactory:
    """LLM 客户端工厂"""

    _clients = {
        "anthropic": AnthropicClient,
        "openai": OpenAIClient,
        "azure": OpenAIClient,  # Azure 也是 OpenAI 兼容格式
        "local": OpenAIClient,  # 本地模型通常使用 OpenAI 兼容 API
    }

    @classmethod
    def create(cls, config: Dict[str, Any]) -> BaseLLMClient:
        """创建 LLM 客户端"""
        provider = config.get("provider", "openai")

        # 加载环境变量
        api_key = config.get("api_key", "")
        if api_key.startswith("${") and api_key.endswith("}"):
            env_var = api_key[2:-1]
            config["api_key"] = os.getenv(env_var)

        if provider not in cls._clients:
            raise ValueError(f"不支持的 LLM provider: {provider}")

        return cls._clients[provider](config)


class ConfigurableLLMClient:
    """
    可配置的 LLM 客户端包装器
    支持从配置文件加载、切换 profile
    """

    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self.config = self._load_config()
        self.client = self._create_client()

    def _load_config(self) -> Dict[str, Any]:
        """加载配置文件"""
        if not os.path.exists(self.config_path):
            return {}

        with open(self.config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        return config.get("llm", {})

    def _create_client(self) -> BaseLLMClient:
        """创建当前配置的客户端"""
        return LLMClientFactory.create(self.config)

    def switch_profile(self, profile_name: str):
        """切换到指定 profile"""
        profiles = self.config.get("profiles", {})
        if profile_name not in profiles:
            raise ValueError(f"Profile '{profile_name}' 不存在")

        # 合并基础配置和 profile 配置
        profile_config = {**self.config, **profiles[profile_name]}
        self.config = profile_config
        self.client = LLMClientFactory.create(profile_config)

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        """便捷方法：生成响应"""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        return await self.client.generate(messages, temperature, max_tokens)

    async def stream_generate(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncGenerator[str, None]:
        """便捷方法：流式生成"""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        async for chunk in self.client.stream_generate(messages, temperature, max_tokens):
            yield chunk
