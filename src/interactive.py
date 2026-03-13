"""
交互式界面
提供半自动流程的用户交互
"""

import asyncio
import sys
import traceback
from datetime import datetime
from typing import List, Optional

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.live import Live
from rich.markdown import Markdown

from .retriever.base import RetrievedContent, SourceType
from .retriever.search_engine import SearchEngineRetriever
from .retriever.arxiv import ArxivRetriever
from .retriever.github import GitHubRetriever
from .filter.content_filter import ContentFilter
from .generator.doc_generator import DocumentGenerator, DocumentOutline, Section
from .exporter.exporters import DocumentExporter
from .workflow_state import WorkflowStateManager, WorkflowState, WorkflowStep


console = Console()


class InteractiveWorkflow:
    """交互式工作流"""

    @staticmethod
    def _make_serializable(obj):
        """使对象可 JSON 序列化"""
        if isinstance(obj, SourceType):
            return obj.value
        if isinstance(obj, datetime):
            return obj.isoformat()
        return obj

    def __init__(self, config: dict):
        self.config = config
        self.retrievers = self._init_retrievers()
        self.filter = ContentFilter(config.get("filter", {}))
        self.generator = DocumentGenerator()
        self.exporter = DocumentExporter(config.get("output", {}))
        self.state_manager = WorkflowStateManager()
        self.state = WorkflowState()

    def _init_retrievers(self):
        """初始化检索器"""
        retrievers = []

        search_config = self.config.get("retriever", {}).get("search_engine", {})
        if search_config.get("enabled", True):
            retrievers.append(("搜索引擎", SearchEngineRetriever(search_config)))

        arxiv_config = self.config.get("retriever", {}).get("arxiv", {})
        if arxiv_config.get("enabled", True):
            retrievers.append(("学术论文", ArxivRetriever(arxiv_config)))

        github_config = self.config.get("retriever", {}).get("github", {})
        if github_config.get("enabled", True):
            retrievers.append(("GitHub", GitHubRetriever(github_config)))

        return retrievers

    async def run(self):
        """运行交互式流程"""
        console.print(Panel.fit(
            "[bold blue]知识文档自动生成系统[/bold blue]\n"
            "[dim]半自动模式 - 每一步都可以审查和确认[/dim]"
        ))

        # 检查是否有未完成的状态
        if await self._check_resume():
            return

        # Step 1: 输入主题
        topic = self._input_topic()

        # Step 2: 选择文档类型
        doc_type = self._select_doc_type()

        # Step 3: 检索资料
        sources = await self._retrieve_sources(topic)
        if not sources:
            console.print("[red]未找到相关资源，请尝试其他主题[/red]")
            return

        # Step 4: 筛选资源
        filtered_sources = self._filter_sources(sources)
        if not filtered_sources:
            console.print("[red]筛选后没有剩余资源[/red]")
            return

        # Step 5: 确认/编辑大纲
        outline = await self._generate_and_confirm_outline(topic, filtered_sources, doc_type)
        if outline is None:
            console.print("[yellow]用户取消[/yellow]")
            return

        # Step 6: 生成内容
        content = await self._generate_content(outline, filtered_sources)

        # Step 7: 导出
        output_path = self._export_document(content)

        console.print(f"\n[green]✓ 文档生成完成: {output_path}[/green]")

    async def _check_resume(self) -> bool:
        """检查是否有未完成的状态，如果有则提示恢复"""
        if not self.state_manager.exists():
            return False

        age = self.state_manager.get_state_age_minutes()
        if age is None or age > 1440:  # 超过24小时的状态忽略
            self.state_manager.clear()
            return False

        console.print("\n[yellow]⚠ 发现未完成的工作流[/yellow]")
        state = self.state_manager.load()
        if state:
            console.print(f"  主题: {state.topic}")
            console.print(f"  当前步骤: {self._get_step_name(state.step)}")
            console.print(f"  创建时间: {state.created_at}")

            if Confirm.ask("是否恢复上次工作流？", default=True):
                await self._resume_workflow(state)
                return True
            else:
                self.state_manager.clear()

        return False

    def _get_step_name(self, step: str) -> str:
        """获取步骤的中文名称"""
        names = {
            WorkflowStep.INIT.value: "初始化",
            WorkflowStep.TOPIC_INPUT.value: "主题输入",
            WorkflowStep.DOC_TYPE_SELECTED.value: "文档类型选择",
            WorkflowStep.SOURCES_RETRIEVED.value: "资料检索",
            WorkflowStep.SOURCES_FILTERED.value: "资料筛选",
            WorkflowStep.OUTLINE_CONFIRMED.value: "大纲确认",
            WorkflowStep.CONTENT_GENERATING.value: "内容生成中",
            WorkflowStep.CONTENT_COMPLETED.value: "内容生成完成",
            WorkflowStep.EXPORTED.value: "已导出",
        }
        return names.get(step, step)

    async def _resume_workflow(self, state: WorkflowState):
        """恢复工作流"""
        console.print(f"\n[green]正在恢复工作流...[/green]")
        self.state = state

        try:
            step = state.step

            if step == WorkflowStep.INIT.value:
                # 从第一步开始
                await self._run_from_start()
                return

            # 恢复主题和类型
            topic = state.topic
            doc_type = state.doc_type

            if step in [WorkflowStep.TOPIC_INPUT.value, WorkflowStep.DOC_TYPE_SELECTED.value]:
                # 需要重新检索
                await self._run_from_retrieval(topic, doc_type)
                return

            # 恢复检索结果 (将字符串转回枚举和 datetime)
            def restore_retrieved_content(s_data: dict) -> RetrievedContent:
                """从字典恢复 RetrievedContent"""
                s_data_copy = s_data.copy()
                # 恢复 source_type
                s_data_copy['source_type'] = SourceType(s_data['source_type'])
                # 恢复 publish_date
                if s_data.get('publish_date') and isinstance(s_data['publish_date'], str):
                    try:
                        s_data_copy['publish_date'] = datetime.fromisoformat(s_data['publish_date'])
                    except ValueError:
                        s_data_copy['publish_date'] = None
                return RetrievedContent(**s_data_copy)

            sources = [restore_retrieved_content(s) for s in state.filtered_sources]

            if step == WorkflowStep.SOURCES_RETRIEVED.value:
                # 从筛选开始
                await self._run_from_filter(topic, doc_type, sources)
                return

            if step == WorkflowStep.SOURCES_FILTERED.value:
                # 从大纲生成开始
                await self._run_from_outline(topic, doc_type, sources)
                return

            def _restore_outline(outline_data: dict) -> DocumentOutline:
                """从字典恢复大纲对象"""
                sections_data = outline_data.pop('sections', [])
                sections = [Section(**s) for s in sections_data]
                return DocumentOutline(**outline_data, sections=sections)

            if step == WorkflowStep.OUTLINE_CONFIRMED.value:
                # 恢复大纲
                outline = _restore_outline(state.outline.copy())
                await self._run_from_content(outline, sources, state)
                return

            if step == WorkflowStep.CONTENT_GENERATING.value:
                # 继续内容生成
                outline = _restore_outline(state.outline.copy())
                await self._run_from_content(outline, sources, state)
                return

            if step == WorkflowStep.CONTENT_COMPLETED.value:
                # 从导出开始
                self.state = state
                outline = _restore_outline(state.outline.copy())
                content = state.generated_content
                output_path = self._export_document(content)
                console.print(f"\n[green]✓ 文档生成完成: {output_path}[/green]")
                self.state_manager.clear()
                return

        except Exception as e:
            await self._handle_error(e)
            return

    async def _run_from_start(self):
        """从头开始运行"""
        topic = self._input_topic()
        doc_type = self._select_doc_type()
        await self._run_from_retrieval(topic, doc_type)

    async def _run_from_retrieval(self, topic: str, doc_type: str):
        """从检索开始运行"""
        sources = await self._retrieve_sources(topic)
        if not sources:
            console.print("[red]未找到相关资源[/red]")
            return
        await self._run_from_filter(topic, doc_type, sources)

    async def _run_from_filter(self, topic: str, doc_type: str, sources: List[RetrievedContent]):
        """从筛选开始运行"""
        filtered = self._filter_sources(sources)
        if not filtered:
            console.print("[red]筛选后没有剩余资源[/red]")
            return
        await self._run_from_outline(topic, doc_type, filtered)

    async def _run_from_outline(self, topic: str, doc_type: str, sources: List[RetrievedContent]):
        """从大纲生成开始运行"""
        outline = await self._generate_and_confirm_outline(topic, sources, doc_type)
        if outline is None:
            console.print("[yellow]用户取消[/yellow]")
            return
        await self._run_from_content(outline, sources, None)

    async def _run_from_content(self, outline: DocumentOutline, sources: List[RetrievedContent], state: Optional[WorkflowState]):
        """从内容生成开始运行（支持断点续传）"""
        content = await self._generate_content_resumable(outline, sources, state)
        if content:
            output_path = self._export_document(content)
            console.print(f"\n[green]✓ 文档生成完成: {output_path}[/green]")
            self.state_manager.clear()

    async def _handle_error(self, error: Exception):
        """处理错误并保存状态"""
        error_msg = str(error)
        self.state.last_error = error_msg
        self.state.error_count += 1
        self.state_manager.save(self.state)

        console.print("\n[red]✗ 发生错误[/red]")
        console.print(f"[red]{error_msg[:200]}[/red]")

        # 输出到 stderr 避免污染 stdout
        sys.stderr.write("\n详细错误信息:\n")
        sys.stderr.write(traceback.format_exc())

        console.print("\n[yellow]当前状态已保存，下次运行可恢复[/yellow]")

    def _input_topic(self) -> str:
        """输入主题"""
        console.print("\n[bold]Step 1: 输入主题[/bold]")
        topic = Prompt.ask("请输入你想了解的主题")
        self.state.topic = topic
        self.state.step = WorkflowStep.TOPIC_INPUT.value
        self.state_manager.save(self.state)
        return topic

    def _select_doc_type(self) -> str:
        """选择文档类型"""
        console.print("\n[bold]Step 2: 选择文档类型[/bold]")

        doc_types = self.config.get("generator", {}).get("doc_types", {
            "tutorial": {"name": "入门教程", "description": "循序渐进的学习指南"},
            "reference": {"name": "参考文档", "description": "详细的技术参考"},
            "comparison": {"name": "对比评测", "description": "多方案对比分析"},
        })

        table = Table(title="文档类型")
        table.add_column("编号", style="cyan")
        table.add_column("类型", style="green")
        table.add_column("描述", style="dim")

        type_list = list(doc_types.items())
        for i, (key, info) in enumerate(type_list, 1):
            table.add_row(str(i), info["name"], info.get("description", ""))

        console.print(table)

        choice = Prompt.ask(
            "请选择文档类型",
            choices=[str(i) for i in range(1, len(type_list) + 1)],
            default="1"
        )

        doc_type = type_list[int(choice) - 1][0]
        self.state.doc_type = doc_type
        self.state.step = WorkflowStep.DOC_TYPE_SELECTED.value
        self.state_manager.save(self.state)
        return doc_type

    async def _retrieve_sources(self, topic: str) -> List[RetrievedContent]:
        """检索资源"""
        console.print("\n[bold]Step 3: 检索资源[/bold]")

        all_sources = []

        try:
            for name, retriever in self.retrievers:
                if not retriever.is_available():
                    console.print(f"[dim]{name}: 未配置，跳过[/dim]")
                    continue

                with console.status(f"[bold green]正在从 {name} 检索..."):
                    try:
                        sources = await retriever.search(topic, max_results=5)
                        console.print(f"[green]✓ {name}: 找到 {len(sources)} 条结果[/green]")
                        all_sources.extend(sources)
                    except Exception as e:
                        console.print(f"[red]✗ {name}: {str(e)[:50]}[/red]")

            # 保存检索结果 (将 SourceType 枚举和 datetime 转换为字符串)
            serializable_sources = []
            for s in all_sources:
                d = {k: self._make_serializable(v) for k, v in s.__dict__.items()}
                serializable_sources.append(d)
            self.state.sources = serializable_sources
            self.state.step = WorkflowStep.SOURCES_RETRIEVED.value
            self.state_manager.save(self.state)

        except Exception as e:
            await self._handle_error(e)
            raise

        return all_sources

    def _filter_sources(self, sources: List[RetrievedContent]) -> List[RetrievedContent]:
        """筛选资源"""
        console.print("\n[bold]Step 4: 筛选资源[/bold]")

        try:
            # 显示原始结果
            table = Table(title=f"检索结果 (共 {len(sources)} 条)")
            table.add_column("#", style="cyan", width=3)
            table.add_column("来源", style="magenta", width=12)
            table.add_column("标题", style="green", max_width=40)
            table.add_column("权威性", width=8)
            table.add_column("URL", style="dim", max_width=30)

            for i, s in enumerate(sources, 1):
                auth = f"{s.authority_score:.2f}"
                table.add_row(str(i), s.source_type.value, s.title[:40], auth, s.url[:40])

            console.print(table)

            if not Confirm.ask("是否继续进行筛选？"):
                return sources

            # 执行筛选
            filtered = self.filter.filter_all(sources)
            removed = len(sources) - len(filtered)

            console.print(f"[dim]筛选完成: 保留 {len(filtered)} 条，过滤 {removed} 条[/dim]")

            # 允许用户手动选择/取消
            if Confirm.ask("是否需要手动调整选择的资源？"):
                filtered = self._manual_select(filtered)

            # 保存筛选结果 (将 SourceType 枚举和 datetime 转换为字符串)
            serializable_filtered = []
            for s in filtered:
                d = {k: self._make_serializable(v) for k, v in s.__dict__.items()}
                serializable_filtered.append(d)
            self.state.filtered_sources = serializable_filtered
            self.state.step = WorkflowStep.SOURCES_FILTERED.value
            self.state_manager.save(self.state)

            return filtered

        except Exception as e:
            self._handle_error_sync(e)
            raise

    def _handle_error_sync(self, error: Exception):
        """同步处理错误"""
        error_msg = str(error)
        self.state.last_error = error_msg
        self.state.error_count += 1
        self.state_manager.save(self.state)

        console.print("\n[red]✗ 发生错误[/red]")
        console.print(f"[red]{error_msg[:200]}[/red]")
        console.print("\n[yellow]当前状态已保存，下次运行可恢复[/yellow]")

    def _manual_select(self, sources: List[RetrievedContent]) -> List[RetrievedContent]:
        """手动选择资源"""
        selected = []
        for i, s in enumerate(sources, 1):
            if Confirm.ask(f"[{i}/{len(sources)}] 保留: {s.title[:50]}...?", default=True):
                selected.append(s)
        return selected

    async def _generate_and_confirm_outline(
        self,
        topic: str,
        sources: List[RetrievedContent],
        doc_type: str
    ) -> Optional[DocumentOutline]:
        """生成并确认大纲"""
        console.print("\n[bold]Step 5: 生成文档大纲[/bold]")

        try:
            with console.status("[bold green]AI 正在生成大纲..."):
                outline = await self.generator.generate_outline(topic, sources, doc_type)

            # 显示大纲
            console.print(f"\n[bold]{outline.title}[/bold]")
            console.print(f"[dim]类型: {outline.doc_type} | 目标读者: {outline.target_audience} | 预估篇幅: {outline.estimated_length}[/dim]\n")

            for section in outline.sections:
                level_prefix = "  " * (section.level - 2)
                console.print(f"{level_prefix}[cyan]•[/cyan] {section.title}")

            # 确认或编辑
            action = Prompt.ask(
                "\n确认大纲？",
                choices=["confirm", "edit", "cancel"],
                default="confirm"
            )

            if action == "cancel":
                return None
            elif action == "edit":
                outline = self._edit_outline(outline)

            # 保存大纲 (Section 对象转字典)
            outline_dict = outline.__dict__.copy()
            outline_dict['sections'] = [
                {'title': s.title, 'level': s.level, 'content': s.content}
                for s in outline.sections
            ]
            self.state.outline = outline_dict
            self.state.total_sections = len(outline.sections)
            self.state.step = WorkflowStep.OUTLINE_CONFIRMED.value
            self.state_manager.save(self.state)

            return outline

        except Exception as e:
            await self._handle_error(e)
            raise

    def _edit_outline(self, outline: DocumentOutline) -> DocumentOutline:
        """编辑大纲"""
        console.print("[yellow]大纲编辑功能（简化版）[/yellow]")
        console.print("输入新的章节标题，用逗号分隔，或留空保持原样:")

        new_titles = Prompt.ask("新章节列表").strip()
        if new_titles:
            titles = [t.strip() for t in new_titles.split(",")]
            outline.sections = [
                Section(title=t, level=2) for t in titles
            ]

        return outline

    async def _generate_content(
        self,
        outline: DocumentOutline,
        sources: List[RetrievedContent]
    ) -> str:
        """生成文档内容"""
        return await self._generate_content_resumable(outline, sources, None)

    async def _generate_content_resumable(
        self,
        outline: DocumentOutline,
        sources: List[RetrievedContent],
        state: Optional[WorkflowState]
    ) -> str:
        """生成文档内容（支持断点续传）"""
        console.print("\n[bold]Step 6: 生成文档内容[/bold]")

        # 确定开始位置
        start_index = 0
        content_parts = []
        completed_sections = []

        if state and state.step == WorkflowStep.CONTENT_GENERATING.value:
            # 恢复进度
            start_index = state.current_section_index
            content_parts = [state.generated_content] if state.generated_content else []
            completed_sections = state.completed_sections[:]
            console.print(f"[yellow]从中断位置恢复: 章节 {start_index + 1}/{state.total_sections}[/yellow]")
        else:
            # 生成 frontmatter
            content_parts = [
                f"---",
                f"title: {outline.title}",
                f"type: {outline.doc_type}",
                f"audience: {outline.target_audience}",
                f"generated_at: {datetime.now().isoformat()}",
                f"---",
                "",
                f"# {outline.title}",
                "",
            ]

        # 更新状态 (Section 对象转字典)
        outline_dict = outline.__dict__.copy()
        outline_dict['sections'] = [
            {'title': s.title, 'level': s.level, 'content': s.content}
            for s in outline.sections
        ]
        self.state.outline = outline_dict
        self.state.total_sections = len(outline.sections)
        self.state.step = WorkflowStep.CONTENT_GENERATING.value
        self.state.generated_content = "\n".join(content_parts)
        self.state_manager.save(self.state)

        # 逐节生成
        confirm_sections = self.config.get("generator", {}).get("confirm_sections", False)

        try:
            for i, section in enumerate(outline.sections[start_index:], start_index + 1):
                console.print(f"\n[dim]正在生成 {i}/{len(outline.sections)}: {section.title}...[/dim]")

                if confirm_sections:
                    if not Confirm.ask(f"生成章节 '{section.title}'?", default=True):
                        continue

                # 生成章节内容
                section_content = await self.generator.generate_section(
                    section, sources, outline
                )

                content_parts.append(section_content)
                content_parts.append("")

                # 保存进度
                completed_sections.append(section.title)
                self.state.current_section_index = i
                self.state.completed_sections = completed_sections
                self.state.generated_content = "\n".join(content_parts)
                self.state_manager.save(self.state)

            # 完成
            self.state.step = WorkflowStep.CONTENT_COMPLETED.value
            self.state_manager.save(self.state)

            return "\n".join(content_parts)

        except Exception as e:
            # 保存当前进度
            self.state.current_section_index = i - 1 if 'i' in locals() else start_index
            self.state.completed_sections = completed_sections
            self.state.generated_content = "\n".join(content_parts)
            await self._handle_error(e)
            raise

    def _export_document(self, content: str) -> str:
        """导出文档"""
        console.print("\n[bold]Step 7: 导出文档[/bold]")

        try:
            # 选择格式
            fmt = Prompt.ask(
                "选择导出格式",
                choices=["markdown", "pdf", "docx"],
                default="markdown"
            )

            # 选择路径
            default_path = self.config.get("output", {}).get("output_dir", "./output")
            output_path = Prompt.ask(
                "输出路径",
                default=f"{default_path}/document.{fmt if fmt != 'markdown' else 'md'}"
            )

            with console.status(f"[bold green]导出 {fmt}..."):
                path = self.exporter.export(content, output_path, fmt)

            # 更新状态为已完成
            self.state.step = WorkflowStep.EXPORTED.value
            self.state_manager.save(self.state)

            return path

        except Exception as e:
            self._handle_error_sync(e)
            raise


async def main():
    """主入口"""
    import yaml

    # 加载配置
    config_path = "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    workflow = InteractiveWorkflow(config)
    await workflow.run()


if __name__ == "__main__":
    asyncio.run(main())
