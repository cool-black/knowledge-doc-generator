# 知识文档自动生成系统

一个智能化的知识文档生成工具，支持从多源检索、智能筛选到自动生成结构化文档的完整流程。

## 特性

- **多源检索**：整合搜索引擎、arXiv 论文、GitHub 高星仓库
- **智能筛选**：基于权威性、相关性、去重等多维度过滤
- **可配置 LLM**：支持 OpenAI、Anthropic、Azure、本地模型
- **半自动流程**：人机协作，每步可审查和确认
- **多格式导出**：Markdown、PDF、Word

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
# LLM API Keys
export ANTHROPIC_API_KEY="your-key"
export OPENAI_API_KEY="your-key"

# 搜索 API (可选，用于网页搜索)
export SERPER_API_KEY="your-key"

# GitHub API (可选，提高速率限制)
export GITHUB_API_KEY="your-key"
```

### 3. 运行

#### 交互式模式（推荐）

```bash
python -m src.main interactive
```

#### 快速生成（自动模式）

```bash
python -m src.main generate "Transformer 架构详解" --type tutorial
```

## 项目结构

```
knowledge-doc-generator/
├── config.yaml              # 主配置文件
├── requirements.txt
├── README.md
└── src/
    ├── main.py              # CLI 入口
    ├── interactive.py       # 交互式工作流
    ├── retriever/           # 检索层
    │   ├── base.py
    │   ├── search_engine.py # 搜索引擎
    │   ├── arxiv.py         # 论文检索
    │   └── github.py        # GitHub检索
    ├── filter/              # 筛选层
    │   └── content_filter.py
    ├── generator/           # 生成层
    │   ├── llm_client.py    # 可配置 LLM
    │   └── doc_generator.py # 文档生成
    └── exporter/            # 输出层
        └── exporters.py
```

## 配置说明

### LLM 配置

支持多种 provider，可快速切换：

```yaml
llm:
  provider: anthropic  # openai | anthropic | azure | local
  api_key: ${ANTHROPIC_API_KEY}
  model: claude-3-5-sonnet-20241022

  # 快速切换配置
  profiles:
    fast:
      provider: openai
      model: gpt-3.5-turbo
    local:
      provider: local
      base_url: http://localhost:11434/v1
      model: llama2
```

### 检索配置

```yaml
retriever:
  search_engine:
    provider: serper
    api_key: ${SERPER_API_KEY}

  arxiv:
    enabled: true
    max_results: 10

  github:
    enabled: true
    min_stars: 100
```

## 工作流程

```
1. 输入主题
2. 选择文档类型（教程/参考/对比）
3. 多源检索（网页/论文/GitHub）
4. 智能筛选（去重/权威性/相关性）
5. 生成并确认大纲
6. 逐节生成内容
7. 导出为所需格式
```

## 使用示例

### 生成入门教程

```bash
python -m src.main generate "PyTorch 入门教程" \
  --type tutorial \
  --format markdown \
  --output ./docs
```

### 生成技术对比

```bash
python -m src.main generate "GPT vs Claude 对比" \
  --type comparison \
  --format pdf
```

## 注意事项

1. **API 限制**：arXiv 和 GitHub 有速率限制，大量检索时请注意
2. **PDF 导出**：需要安装 weasyprint，Windows 用户可能需要额外配置
3. **内容准确性**：AI 生成的内容可能存在错误，请人工核实关键信息

## 未来规划

- [ ] Embedding 语义去重
- [ ] 更多文档类型（研究报告、API 文档等）
- [ ] 文档模板自定义
- [ ] 增量更新已有文档
- [ ] 多语言支持
