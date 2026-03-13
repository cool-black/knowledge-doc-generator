"""
知识文档自动生成系统
主入口程序
"""

import asyncio
import os
import sys
from pathlib import Path

import typer
import yaml
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

# 加载环境变量
load_dotenv()

app = typer.Typer(help="知识文档自动生成系统")


def run_async(coro):
    """安全地运行异步函数，避免 Windows 上的事件循环警告"""
    if sys.platform == "win32":
        # Windows 上需要特殊处理 ProactorEventLoop
        loop = asyncio.ProactorEventLoop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(coro)
        finally:
            # 清理所有挂起的任务
            try:
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            except Exception:
                pass
            # 强制关闭所有 transport 避免 __del__ 警告
            try:
                import _socket
                loop._proactor.close()
            except Exception:
                pass
            try:
                loop.close()
            except Exception:
                pass
    else:
        return asyncio.run(coro)
console = Console()


def load_config(config_path: str = "config.yaml") -> dict:
    """加载配置文件"""
    if not os.path.exists(config_path):
        console.print(f"[red]配置文件不存在: {config_path}[/red]")
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@app.command()
def interactive(
    config: str = typer.Option("config.yaml", "--config", "-c", help="配置文件路径"),
):
    """启动交互式模式（半自动）"""
    from .interactive import InteractiveWorkflow

    cfg = load_config(config)
    workflow = InteractiveWorkflow(cfg)
    run_async(workflow.run())


@app.command()
def generate(
    topic: str = typer.Argument(..., help="文档主题"),
    doc_type: str = typer.Option("tutorial", "--type", "-t", help="文档类型: tutorial, reference, comparison"),
    output: str = typer.Option("./output", "--output", "-o", help="输出目录"),
    format: str = typer.Option("markdown", "--format", "-f", help="输出格式: markdown, pdf, docx"),
    config: str = typer.Option("config.yaml", "--config", "-c", help="配置文件路径"),
    auto: bool = typer.Option(False, "--auto", "-a", help="全自动模式（跳过确认）"),
):
    """快速生成文档（自动模式）"""
    console.print(Panel.fit(f"[bold blue]生成文档: {topic}[/bold blue]"))

    cfg = load_config(config)

    # 设置输出目录
    cfg["output"]["output_dir"] = output
    cfg["output"]["default_format"] = format

    if auto:
        cfg["generator"]["confirm_outline"] = False
        cfg["generator"]["confirm_sections"] = False

    from .interactive import InteractiveWorkflow
    workflow = InteractiveWorkflow(cfg)
    run_async(workflow.run())


@app.command()
def config_template(
    output: str = typer.Option("config.yaml", "--output", "-o", help="输出配置文件路径"),
):
    """生成配置文件模板"""
    template = """# 知识文档生成器配置

llm:
  provider: anthropic
  api_key: ${ANTHROPIC_API_KEY}
  model: claude-3-5-sonnet-20241022
  temperature: 0.3
  max_tokens: 4096

retriever:
  search_engine:
    provider: serper
    api_key: ${SERPER_API_KEY}
    max_results: 10

  arxiv:
    enabled: true
    max_results: 10

  github:
    enabled: true
    api_key: ${GITHUB_API_KEY}
    min_stars: 100
    max_results: 10

filter:
  min_authority_score: 0.6
  dedup_threshold: 0.85
  min_content_length: 500

generator:
  confirm_outline: true
  confirm_sections: false

output:
  default_format: markdown
  output_dir: ./output
"""
    with open(output, "w", encoding="utf-8") as f:
        f.write(template)

    console.print(f"[green]配置文件模板已生成: {output}[/green]")


if __name__ == "__main__":
    app()
