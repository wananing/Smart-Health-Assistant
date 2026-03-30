# RAG Knowledge Base — Smart Health Assistant

[中文文档 ↓](#rag-知识库——大健康智能助手)

---

## Overview

The RAG (Retrieval-Augmented Generation) module augments the four specialized agents with a curated, authoritative knowledge base. Instead of relying solely on the LLM's parametric knowledge, agents retrieve relevant chunks from domain-specific documents before generating responses — improving factual accuracy and reducing hallucination on medical and insurance topics.

## Architecture

```
User Query
    │
    ▼
Agent Node (advisor / clinic / report / insurance)
    │
    ├─ aretrieve(query, k=3)
    │       │
    │       ├─ BM25 Retriever (30%)   ← exact keyword matching
    │       └─ Chroma/FAISS/… (70%)  ← dense MMR similarity
    │             └─ EnsembleRetriever (Reciprocal Rank Fusion)
    │
    ├─ format_context(docs)
    │       └─ "[source · section]\ncontent" blocks
    │
    └─ LLM call with augmented system prompt
              └─ "## 参考知识库\n{context}"
```

For the **insurance agent**, retrieval is exposed as an additional `search_insurance_policy` tool that the ReAct agent calls on demand for policy questions.

## Retrieval Strategy

| Component | Choice | Why |
|---|---|---|
| Sparse retrieval | BM25 (30%) | Exact match for medical terms: 高血压, 血红蛋白, ICD codes |
| Dense retrieval | Chroma + MMR (70%) | Semantic similarity with diversity enforcement |
| Fusion | Reciprocal Rank Fusion | Merges both ranked lists without manual score normalization |
| k per query | 3 chunks | ~400 tokens overhead — balances context richness vs. prompt size |

## Knowledge Base Documents

| File | Content | Approx. Chunks |
|---|---|---|
| `medical_knowledge.md` | 高血压, 2型糖尿病, 感冒/流感, 冠心病, OTC药参考 | ~14 |
| `insurance_policies.md` | 门诊/住院报销, 慢性病政策, 异地就医, 申请流程 | ~12 |
| `lab_reference.md` | 血常规/生化/尿常规正常值, 异常指标临床意义 | ~12 |

All documents are in Chinese and stored in `backend/rag/documents/`.

### Chunking

- Splitter: `RecursiveCharacterTextSplitter` with Chinese-aware separators (`。！？；\n\n\n `)
- Chunk size: 500 characters, overlap: 100 characters
- Documents are first split by `## ` section headers so each chunk carries `{source, section}` metadata

## Pluggable Backends

### Embedding Providers

Set via `EMBEDDING_PROVIDER` in `.env`:

| Value | Model (default) | Notes |
|---|---|---|
| `huggingface` *(default)* | `BAAI/bge-small-zh-v1.5` | Local, ~90 MB, no API key, CPU-only |
| `openai` | `text-embedding-3-small` | API-based, requires `OPENAI_API_KEY` |
| `ark` | `doubao-embedding-large-text-240915` | ByteDance ARK endpoint, reuses `ARK_API_KEY` |

Override the model name with `EMBEDDING_MODEL=<model>`.

### Vector Store Backends

Set via `VECTOR_STORE` in `.env`:

| Value | Description | Extra Config |
|---|---|---|
| `chroma` *(default)* | File-based, zero config | `CHROMA_PERSIST_DIR` (default: `rag/chroma_db`) |
| `faiss` | In-memory + local disk, fast | `FAISS_INDEX_PATH` (default: `rag/faiss_index`) |
| `qdrant` | Production-grade, requires Qdrant server | `QDRANT_URL`, `QDRANT_API_KEY` |
| `pgvector` | PostgreSQL extension | `PGVECTOR_CONNECTION_STRING` |

## Setup

### First-time setup

```bash
cd backend
uv sync                        # install dependencies
cp .env.example .env           # configure API keys
uv run python -m rag.ingest    # build vector store
                               # (downloads ~90 MB embedding model on first run)
```

### Rebuild after changing documents

```bash
uv run python -m rag.ingest --rebuild
```

### Switch to a different backend

```bash
# Use FAISS instead of Chroma
VECTOR_STORE=faiss uv run python -m rag.ingest --rebuild

# Use OpenAI embeddings
EMBEDDING_PROVIDER=openai EMBEDDING_MODEL=text-embedding-3-small \
  uv run python -m rag.ingest --rebuild

# Use Qdrant (requires a running Qdrant instance)
VECTOR_STORE=qdrant QDRANT_URL=http://localhost:6333 \
  uv run python -m rag.ingest --rebuild
```

## Adding Knowledge Documents

1. Create a Markdown file in `backend/rag/documents/` using `## Section Title` headers.
2. Rebuild the index: `uv run python -m rag.ingest --rebuild`

Example document structure:
```markdown
# Document Title

## Section One

Content for section one...

## Section Two

Content for section two...
```

## File Structure

```
backend/rag/
├── __init__.py
├── knowledge_base.py      # HealthKnowledgeBase class — hybrid retrieval, async-safe
├── embeddings.py          # Embedding provider factory
├── vectorstores.py        # Vector store factory
├── ingest.py              # CLI ingestion script
├── documents/
│   ├── medical_knowledge.md
│   ├── insurance_policies.md
│   └── lab_reference.md
└── chroma_db/             # Auto-generated, gitignored
```

---

# RAG 知识库——大健康智能助手

[English Documentation ↑](#rag-knowledge-base--smart-health-assistant)

---

## 概述

RAG（检索增强生成）模块为四个专业智能体提供来自权威知识库的实时支撑。智能体在生成回答前，先从领域专属文档中检索相关内容片段，再结合检索结果进行回答——显著提升了医疗和医保问题的事实准确性，并降低了大模型"幻觉"风险。

## 系统架构

```
用户输入
    │
    ▼
智能体节点（advisor / clinic / report / insurance）
    │
    ├─ aretrieve(query, k=3)
    │       │
    │       ├─ BM25 检索器（30%）  ← 精确关键词匹配
    │       └─ 向量库（70%）       ← 密集语义检索（MMR 多样性）
    │             └─ EnsembleRetriever（倒数排名融合 RRF）
    │
    ├─ format_context(docs)
    │       └─ "[来源 · 章节]\n内容" 格式的引用块
    │
    └─ LLM 调用（系统提示词追加知识库上下文）
              └─ "## 参考知识库\n{context}"
```

**医保智能体**额外将检索能力封装为 `search_insurance_policy` 工具，ReAct 智能体在处理政策类问题时按需调用。

## 检索策略

| 组件 | 选择 | 原因 |
|---|---|---|
| 稀疏检索 | BM25（权重 30%） | 精确匹配医学专业术语：高血压、血红蛋白等 |
| 密集检索 | 向量库 + MMR（权重 70%） | 语义相似度检索，同时保证结果多样性 |
| 融合方式 | 倒数排名融合（RRF） | 合并两路排序结果，无需手动对齐分数尺度 |
| 每次检索数量 | k=3 | 约 400 tokens 额外上下文，在信息量与成本间取得平衡 |

## 知识库文档

| 文件 | 内容 | 估计切片数 |
|---|---|---|
| `medical_knowledge.md` | 高血压、2型糖尿病、感冒/流感、冠心病、常用非处方药 | ~14 |
| `insurance_policies.md` | 门诊/住院报销比例、慢性病特殊政策、异地就医、申请流程 | ~12 |
| `lab_reference.md` | 血常规/生化/尿常规正常值、常见异常指标临床意义 | ~12 |

所有文档均以中文撰写，存放于 `backend/rag/documents/` 目录。

### 文档切片策略

- 切片器：`RecursiveCharacterTextSplitter`，使用中文感知分隔符（`。！？；\n\n\n `）
- 切片大小：500 字符，重叠：100 字符
- 切片前先按 `## ` 标题拆分章节，每个切片附带 `{source, section}` 元数据，便于来源溯源

## 可插拔后端

### 嵌入模型提供商

通过 `.env` 中的 `EMBEDDING_PROVIDER` 配置：

| 值 | 默认模型 | 说明 |
|---|---|---|
| `huggingface`（**默认**） | `BAAI/bge-small-zh-v1.5` | 本地运行，约 90 MB，无需 API Key，CPU 即可 |
| `openai` | `text-embedding-3-small` | 调用 OpenAI API，需配置 `OPENAI_API_KEY` |
| `ark` | `doubao-embedding-large-text-240915` | 字节跳动火山引擎 ARK，复用现有 `ARK_API_KEY` |

通过 `EMBEDDING_MODEL=<模型名>` 可自定义模型。

### 向量数据库后端

通过 `.env` 中的 `VECTOR_STORE` 配置：

| 值 | 说明 | 额外配置项 |
|---|---|---|
| `chroma`（**默认**） | 基于文件，零配置 | `CHROMA_PERSIST_DIR`（默认：`rag/chroma_db`） |
| `faiss` | 内存 + 本地磁盘，速度快 | `FAISS_INDEX_PATH`（默认：`rag/faiss_index`） |
| `qdrant` | 生产级向量库，需部署 Qdrant 服务 | `QDRANT_URL`、`QDRANT_API_KEY` |
| `pgvector` | PostgreSQL 扩展 | `PGVECTOR_CONNECTION_STRING` |

## 快速上手

### 首次初始化

```bash
cd backend
uv sync                        # 安装依赖
cp .env.example .env           # 配置 API Key 等环境变量
uv run python -m rag.ingest    # 构建向量库
                               # （首次运行会自动下载约 90 MB 的嵌入模型）
```

### 更新知识文档后重建索引

```bash
uv run python -m rag.ingest --rebuild
```

### 切换后端

```bash
# 使用 FAISS 替代 Chroma
VECTOR_STORE=faiss uv run python -m rag.ingest --rebuild

# 使用 OpenAI 嵌入模型
EMBEDDING_PROVIDER=openai EMBEDDING_MODEL=text-embedding-3-small \
  uv run python -m rag.ingest --rebuild

# 使用 Qdrant（需先启动 Qdrant 服务）
VECTOR_STORE=qdrant QDRANT_URL=http://localhost:6333 \
  uv run python -m rag.ingest --rebuild
```

## 添加知识文档

1. 在 `backend/rag/documents/` 目录下新建 Markdown 文件，使用 `## 章节标题` 结构。
2. 重建索引：`uv run python -m rag.ingest --rebuild`

文档格式示例：
```markdown
# 文档标题

## 第一章节

第一章节的内容...

## 第二章节

第二章节的内容...
```

## 目录结构

```
backend/rag/
├── __init__.py
├── knowledge_base.py      # HealthKnowledgeBase 类——混合检索，异步安全
├── embeddings.py          # 嵌入模型工厂（环境变量驱动）
├── vectorstores.py        # 向量库工厂（环境变量驱动）
├── ingest.py              # 命令行导入脚本
├── documents/
│   ├── medical_knowledge.md    # 常见疾病知识
│   ├── insurance_policies.md   # 医保政策
│   └── lab_reference.md        # 检验参考范围
└── chroma_db/             # 自动生成，已加入 .gitignore
```
