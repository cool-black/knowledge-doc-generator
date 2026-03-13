"""
文档生成器
根据检索结果生成结构化文档
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import AsyncGenerator, Dict, List, Optional, Literal
import logging
import re

from ..retriever.base import RetrievedContent
from .llm_client import ConfigurableLLMClient


# 配置日志
logger = logging.getLogger(__name__)


class DocType(str, Enum):
    """文档类型枚举"""
    TUTORIAL = "tutorial"
    REFERENCE = "reference"
    COMPARISON = "comparison"


class AudienceLevel(str, Enum):
    """目标受众级别枚举"""
    BEGINNER = "初学者"
    INTERMEDIATE = "中级开发者"
    EXPERT = "专家"


class DocumentLength(str, Enum):
    """文档长度枚举"""
    SHORT = "短篇"
    MEDIUM = "中篇"
    LONG = "长篇"


@dataclass
class Section:
    """文档章节"""
    title: str
    level: int  # 1, 2, 3...
    content: str = ""
    source_indices: List[int] = field(default_factory=list)  # 引用来源的索引列表


@dataclass
class DocumentOutline:
    """文档大纲"""
    title: str
    doc_type: str
    sections: List[Section]
    target_audience: str = ""
    estimated_length: str = ""


class OutlineGenerator:
    """大纲生成器"""

    SYSTEM_PROMPT = """你是一个专业的技术文档大纲规划师。
根据用户提供的主题和检索结果，设计一份清晰、结构化的文档大纲。

要求：
1. 大纲要循序渐进，由浅入深
2. 每个章节要有明确的重点
3. 考虑目标读者的知识背景
4. 合理分配篇幅权重

输出格式：
# 文档标题
doc_type: [tutorial|reference|comparison]
target_audience: [初学者|中级开发者|专家]
estimated_length: [短篇|中篇|长篇]

## 1. 章节标题
- 要点1
- 要点2

## 2. 章节标题
- 要点1
- 要点2
"""

    # 配置常量
    MAX_SOURCES = 5
    MAX_CONTENT_PREVIEW = 500
    MAX_TOPIC_LENGTH = 200

    # 有效的文档类型
    VALID_DOC_TYPES = {"tutorial", "reference", "comparison"}

    def __init__(self, llm_client: ConfigurableLLMClient):
        self.llm = llm_client

    @staticmethod
    def _sanitize_input(text: str, max_length: int = MAX_TOPIC_LENGTH) -> str:
        """清理输入文本，防止提示词注入攻击

        Args:
            text: 原始输入文本
            max_length: 最大允许长度

        Returns:
            清理后的文本
        """
        if not text:
            return ""

        # 限制长度
        if len(text) > max_length:
            text = text[:max_length]

        # 移除潜在的危险字符序列，防止提示词注入
        # 移除花括号（可能被用于提示词模板注入）
        text = text.replace("{", "").replace("}", "")
        # 移除控制字符
        text = re.sub(r'[\x00-\x1F\x7F-\x9F]', '', text)
        # 移除过多的连续特殊字符
        text = re.sub(r'[!?]{3,}', '!!', text)

        return text.strip()

    def _validate_doc_type(self, doc_type: str) -> str:
        """验证文档类型是否有效

        Args:
            doc_type: 文档类型字符串

        Returns:
            有效的文档类型
        """
        if doc_type not in self.VALID_DOC_TYPES:
            logger.warning(f"未知的文档类型: {doc_type}，使用默认值 'tutorial'")
            return "tutorial"
        return doc_type

    def _build_sources_info(self, sources: List[RetrievedContent]) -> str:
        """构建源信息字符串"""
        selected_sources = sources[:self.MAX_SOURCES]
        source_parts = [
            f"[{i+1}] {s.title} ({s.source_type.value})\n{s.content[:self.MAX_CONTENT_PREVIEW]}..."
            for i, s in enumerate(selected_sources)
        ]
        return "\n\n".join(source_parts)

    async def generate(
        self,
        topic: str,
        sources: List[RetrievedContent],
        doc_type: Literal["tutorial", "reference", "comparison"] = "tutorial",
        target_audience: Literal["初学者", "中级开发者", "专家"] = "中级开发者",
    ) -> DocumentOutline:
        """生成文档大纲"""
        # 输入验证和清理
        sanitized_topic = self._sanitize_input(topic)
        validated_doc_type = self._validate_doc_type(doc_type)

        sources_info = self._build_sources_info(sources)

        user_prompt = f"""主题：{sanitized_topic}
文档类型：{validated_doc_type}
目标读者：{target_audience}

参考来源：
{sources_info}

请根据以上信息，设计一份文档大纲。"""

        try:
            response = await self.llm.generate(
                system_prompt=self.SYSTEM_PROMPT,
                user_prompt=user_prompt,
            )
            # 解析大纲
            return self._parse_outline(response.content)
        except Exception as e:
            logger.error(f"生成大纲时出错: {e}")
            # 返回一个默认的大纲作为降级方案
            return self._create_default_outline(topic, doc_type, target_audience)

    def _create_default_outline(
        self,
        topic: str,
        doc_type: str,
        target_audience: str = "中级开发者"
    ) -> DocumentOutline:
        """创建默认大纲（降级方案）"""
        return DocumentOutline(
            title=topic,
            doc_type=doc_type,
            sections=[
                Section(title="简介", level=2),
                Section(title="主要内容", level=2),
                Section(title="总结", level=2),
            ],
            target_audience=target_audience,
            estimated_length=DocumentLength.MEDIUM.value,
        )

    @staticmethod
    def _parse_heading_level(line: str) -> tuple[int, str] | None:
        """解析 Markdown 标题行，返回标题级别和标题内容

        Args:
            line: 行内容

        Returns:
            (级别, 标题内容) 或 None（如果不是标题）
        """
        # 匹配 1-6 级标题
        match = re.match(r'^(#{1,6})\s+(.+)$', line)
        if match:
            level = len(match.group(1))
            title = match.group(2).strip()
            return level, title
        return None

    def _parse_outline(self, content: str) -> DocumentOutline:
        """解析 LLM 生成的大纲

        支持解析 1-6 级 Markdown 标题，但通常文档大纲使用 2-3 级。
        """
        lines = content.strip().split("\n")

        title = "未命名文档"
        doc_type = "tutorial"
        target_audience = ""
        estimated_length = ""
        sections: List[Section] = []
        current_section: Optional[Section] = None
        content_lines: List[str] = []

        def save_current_section() -> None:
            """保存当前章节到列表"""
            nonlocal current_section, content_lines
            if current_section is not None:
                if content_lines:
                    current_section.content = "\n".join(content_lines)
                    content_lines = []
                sections.append(current_section)
                current_section = None

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 提取元数据
            if line.startswith("doc_type:"):
                doc_type = self._validate_doc_type(self._extract_metadata_value(line))
            elif line.startswith("target_audience:"):
                target_audience = self._extract_metadata_value(line)
            elif line.startswith("estimated_length:"):
                estimated_length = self._extract_metadata_value(line)
            # 提取文档标题（一级标题）
            elif line.startswith("# ") and not line.startswith("##"):
                title = line[2:].strip()
            # 提取章节（二级及以上标题）
            else:
                heading = self._parse_heading_level(line)
                if heading and heading[0] >= 2:
                    save_current_section()
                    current_section = Section(
                        title=heading[1],
                        level=heading[0],
                    )
                # 提取要点
                elif line.startswith("-") and current_section is not None:
                    content_lines.append(line[1:].strip())

        save_current_section()

        return DocumentOutline(
            title=title,
            doc_type=doc_type,
            sections=sections,
            target_audience=target_audience,
            estimated_length=estimated_length,
        )

    @staticmethod
    def _extract_metadata_value(line: str) -> str:
        """从元数据行提取值"""
        parts = line.split(":", 1)
        return parts[1].strip() if len(parts) > 1 else ""


class ContentGenerator:
    """内容生成器"""

    SYSTEM_PROMPT = """你是一个专业的技术文档作者。
根据提供的大纲章节和参考资料，撰写高质量的文档内容。

要求：
1. 内容准确，基于提供的参考资料
2. 语言流畅，易于理解
3. 适当使用以下方式增强可读性：
   - 代码示例（关键实现）
   - 表格（对比信息）
   - Mermaid图表（架构图、流程图，优先用flowchart TD/graph LR）
   - 数学公式（LaTeX格式）
4. 在关键观点后标注引用来源 [1], [2] 等
5. 不要编造信息，如果参考资料不足请明确说明

Mermaid图表示例：
```mermaid
flowchart TD
    A[输入] --> B[编码器]
    B --> C[注意力层]
    C --> D[输出]
```

输出格式：直接输出 Markdown 格式的内容。"""

    # 配置常量
    # 非流式生成时使用的最大内容长度
    # 较大的值允许提供更多上下文，生成更详细的内容
    MAX_CONTENT_LENGTH_FULL = 1000

    # 流式生成时使用的最大内容长度
    # 使用较小的值是为了：
    # 1. 减少初始响应延迟，提升用户体验
    # 2. 降低内存占用，适合长时间流式传输
    # 3. 流式生成通常用于实时预览，完整内容可后续获取
    MAX_CONTENT_LENGTH_STREAM = 800

    DEFAULT_MAX_TOKENS = 4096

    def __init__(self, llm_client: ConfigurableLLMClient):
        self.llm = llm_client
        # 缓存构建的源信息，避免重复处理相同的 sources
        self._sources_cache: Dict[int, str] = {}

    def _build_sources_info(
        self,
        sources: List[RetrievedContent],
        max_length: int = MAX_CONTENT_LENGTH_FULL
    ) -> str:
        """构建源信息字符串

        使用缓存机制避免对相同的 sources 重复构建。
        """
        # 使用 sources 的 id 和 max_length 作为缓存键
        cache_key = (id(sources), max_length)

        if cache_key in self._sources_cache:
            return self._sources_cache[cache_key]

        source_parts = [
            f"[{i+1}] {s.title} ({s.url})\n{s.content[:max_length]}..."
            for i, s in enumerate(sources)
        ]
        result = "\n\n".join(source_parts)

        # 存储到缓存
        self._sources_cache[cache_key] = result
        return result

    def _build_section_prompt(
        self,
        section: Section,
        outline: DocumentOutline,
        sources_info: str,
        include_details: bool = True
    ) -> str:
        """构建章节生成提示词"""
        if include_details:
            return f"""文档标题：{outline.title}
文档类型：{outline.doc_type}
目标读者：{outline.target_audience}

当前章节：{section.title}
章节要点：
{section.content}

参考资料：
{sources_info}

请撰写该章节的详细内容（Markdown格式）。"""
        else:
            return f"""文档标题：{outline.title}
当前章节：{section.title}
章节要点：{section.content}

参考资料：
{sources_info}

请撰写该章节的详细内容（Markdown格式）。"""

    async def generate_section(
        self,
        section: Section,
        sources: List[RetrievedContent],
        outline: DocumentOutline,
    ) -> str:
        """生成单个章节的内容"""
        sources_info = self._build_sources_info(sources, self.MAX_CONTENT_LENGTH_FULL)
        user_prompt = self._build_section_prompt(section, outline, sources_info, include_details=True)

        try:
            response = await self.llm.generate(
                system_prompt=self.SYSTEM_PROMPT,
                user_prompt=user_prompt,
                max_tokens=self.DEFAULT_MAX_TOKENS,
            )
            return response.content
        except Exception as e:
            logger.error(f"生成章节内容时出错 [{section.title}]: {e}")
            return f"## {section.title}\n\n内容生成失败，请稍后重试。"

    async def stream_section(
        self,
        section: Section,
        sources: List[RetrievedContent],
        outline: DocumentOutline,
    ) -> AsyncGenerator[str, None]:
        """流式生成章节内容"""
        sources_info = self._build_sources_info(sources, self.MAX_CONTENT_LENGTH_STREAM)
        user_prompt = self._build_section_prompt(section, outline, sources_info, include_details=False)

        try:
            async for chunk in self.llm.stream_generate(
                system_prompt=self.SYSTEM_PROMPT,
                user_prompt=user_prompt,
            ):
                yield chunk
        except Exception as e:
            logger.error(f"流式生成章节内容时出错 [{section.title}]: {e}")
            yield f"\n\n[错误: 内容生成中断 - {str(e)}]"


class DocumentGenerator:
    """文档生成器主类"""

    def __init__(self, llm_client: Optional[ConfigurableLLMClient] = None):
        self.llm = llm_client or ConfigurableLLMClient()
        self.outline_generator = OutlineGenerator(self.llm)
        self.content_generator = ContentGenerator(self.llm)

    async def generate_outline(
        self,
        topic: str,
        sources: List[RetrievedContent],
        doc_type: Literal["tutorial", "reference", "comparison"] = "tutorial",
        target_audience: Literal["初学者", "中级开发者", "专家"] = "中级开发者",
    ) -> DocumentOutline:
        """生成文档大纲"""
        return await self.outline_generator.generate(topic, sources, doc_type, target_audience)

    async def generate_section(
        self,
        section: Section,
        sources: List[RetrievedContent],
        outline: DocumentOutline,
    ) -> str:
        """生成单个章节"""
        return await self.content_generator.generate_section(section, sources, outline)

    async def stream_section(
        self,
        section: Section,
        sources: List[RetrievedContent],
        outline: DocumentOutline,
    ) -> AsyncGenerator[str, None]:
        """流式生成单个章节"""
        async for chunk in self.content_generator.stream_section(section, sources, outline):
            yield chunk
