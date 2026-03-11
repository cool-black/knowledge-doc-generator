"""
文档生成器
根据检索结果生成结构化文档
"""

from dataclasses import dataclass
from typing import AsyncGenerator, Dict, List, Optional

from ..retriever.base import RetrievedContent
from .llm_client import ConfigurableLLMClient


@dataclass
class Section:
    """文档章节"""
    title: str
    level: int  # 1, 2, 3...
    content: str = ""
    sources: List[RetrievedContent] = None

    def __post_init__(self):
        if self.sources is None:
            self.sources = []


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

    def __init__(self, llm_client: ConfigurableLLMClient):
        self.llm = llm_client

    async def generate(
        self,
        topic: str,
        sources: List[RetrievedContent],
        doc_type: str = "tutorial",
    ) -> DocumentOutline:
        """生成文档大纲"""
        # 构建源信息
        sources_info = "\n\n".join([
            f"[{i+1}] {s.title} ({s.source_type.value})\n{s.content[:500]}..."
            for i, s in enumerate(sources[:5])  # 只使用前5个最相关的源
        ])

        user_prompt = f"""主题：{topic}
文档类型：{doc_type}

参考来源：
{sources_info}

请根据以上信息，设计一份文档大纲。"""

        response = await self.llm.generate(
            system_prompt=self.SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )

        # 解析大纲
        return self._parse_outline(response.content)

    def _parse_outline(self, content: str) -> DocumentOutline:
        """解析 LLM 生成的大纲"""
        lines = content.strip().split("\n")

        title = "未命名文档"
        doc_type = "tutorial"
        target_audience = ""
        estimated_length = ""
        sections = []
        current_section = None

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 提取元数据
            if line.startswith("doc_type:"):
                doc_type = line.split(":", 1)[1].strip()
            elif line.startswith("target_audience:"):
                target_audience = line.split(":", 1)[1].strip()
            elif line.startswith("estimated_length:"):
                estimated_length = line.split(":", 1)[1].strip()
            # 提取标题
            elif line.startswith("# ") and not line.startswith("##"):
                title = line[2:].strip()
            # 提取章节
            elif line.startswith("## "):
                if current_section:
                    sections.append(current_section)
                current_section = Section(
                    title=line[3:].strip(),
                    level=2,
                )
            elif line.startswith("### "):
                if current_section:
                    sections.append(current_section)
                current_section = Section(
                    title=line[4:].strip(),
                    level=3,
                )
            # 提取要点
            elif line.startswith("-") and current_section:
                current_section.content += line[1:].strip() + "\n"

        if current_section:
            sections.append(current_section)

        return DocumentOutline(
            title=title,
            doc_type=doc_type,
            sections=sections,
            target_audience=target_audience,
            estimated_length=estimated_length,
        )


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

    def __init__(self, llm_client: ConfigurableLLMClient):
        self.llm = llm_client

    async def generate_section(
        self,
        section: Section,
        sources: List[RetrievedContent],
        outline: DocumentOutline,
    ) -> str:
        """生成单个章节的内容"""
        # 构建源信息
        sources_info = "\n\n".join([
            f"[{i+1}] {s.title} ({s.url})\n{s.content[:1000]}..."
            for i, s in enumerate(sources)
        ])

        user_prompt = f"""文档标题：{outline.title}
文档类型：{outline.doc_type}
目标读者：{outline.target_audience}

当前章节：{section.title}
章节要点：
{section.content}

参考资料：
{sources_info}

请撰写该章节的详细内容（Markdown格式）。"""

        response = await self.llm.generate(
            system_prompt=self.SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_tokens=4096,
        )

        return response.content

    async def stream_section(
        self,
        section: Section,
        sources: List[RetrievedContent],
        outline: DocumentOutline,
    ) -> AsyncGenerator[str, None]:
        """流式生成章节内容"""
        sources_info = "\n\n".join([
            f"[{i+1}] {s.title}\n{s.content[:800]}..."
            for i, s in enumerate(sources)
        ])

        user_prompt = f"""文档标题：{outline.title}
当前章节：{section.title}
章节要点：{section.content}

参考资料：
{sources_info}

请撰写该章节的详细内容（Markdown格式）。"""

        async for chunk in self.llm.stream_generate(
            system_prompt=self.SYSTEM_PROMPT,
            user_prompt=user_prompt,
        ):
            yield chunk


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
        doc_type: str = "tutorial",
    ) -> DocumentOutline:
        """生成文档大纲"""
        return await self.outline_generator.generate(topic, sources, doc_type)

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
