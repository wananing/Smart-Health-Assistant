"""
RAG Knowledge Base for the Smart Health Assistant.

Retrieval strategy: Hybrid BM25 (30%) + Dense MMR (70%) via EnsembleRetriever.
  - BM25 catches exact medical term matches (高血压, 血红蛋白, 门诊报销 …)
  - Dense MMR retrieves semantically similar chunks with diversity enforcement
  - EnsembleRetriever merges both lists via Reciprocal Rank Fusion (RRF)

Thread safety: asyncio.Lock + run_in_executor keeps the blocking HuggingFace model
load off the event loop. Double-checked locking prevents duplicate init on concurrent
first requests.
"""
from __future__ import annotations

import asyncio
import re
from functools import lru_cache
from pathlib import Path
from typing import List

from langchain.retrievers import EnsembleRetriever
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document

from rag.embeddings import get_embeddings
from rag.vectorstores import get_vectorstore

DOCS_DIR = Path(__file__).parent / "documents"

# Chinese-aware separators: sentence endings → paragraph breaks → finer boundaries
_CHINESE_SEPARATORS = ["。", "！", "？", "；", "\n\n", "\n", "，", " ", ""]


class HealthKnowledgeBase:
    """
    Hybrid RAG retriever with pluggable embedding and vector-store backends.
    Lazily initialized on first retrieval call.
    """

    def __init__(self) -> None:
        self._retriever: EnsembleRetriever | None = None
        self._initialized = False
        self._lock = asyncio.Lock()

    # ── Initialization ────────────────────────────────────────────────────────

    async def _ensure_initialized(self) -> None:
        """Async-safe lazy init: runs the blocking model load in a thread pool."""
        if self._initialized:
            return
        async with self._lock:
            if self._initialized:
                return  # another coroutine finished init while we waited
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._sync_init)

    def _sync_init(self, *, rebuild: bool = False) -> None:
        """Blocking initialization — called via run_in_executor or directly from CLI."""
        embeddings = get_embeddings()
        documents = self._load_documents()
        vectorstore = get_vectorstore(embeddings, documents, rebuild=rebuild)

        dense_retriever = vectorstore.as_retriever(
            search_type="mmr",
            search_kwargs={"k": 4, "fetch_k": 20},
        )
        sparse_retriever = BM25Retriever.from_documents(documents, k=3)

        self._retriever = EnsembleRetriever(
            retrievers=[sparse_retriever, dense_retriever],
            weights=[0.3, 0.7],
        )
        self._initialized = True

    def rebuild(self) -> None:
        """Drop and rebuild the vector store from source documents (synchronous)."""
        self._initialized = False
        self._retriever = None
        self._sync_init(rebuild=True)

    # ── Document Loading & Chunking ───────────────────────────────────────────

    def _load_documents(self) -> List[Document]:
        """
        Load Markdown files from documents/, split by ## section headers, then
        apply RecursiveCharacterTextSplitter with Chinese-aware separators.
        Each chunk carries {source, section} metadata.
        """
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,
            chunk_overlap=100,
            separators=_CHINESE_SEPARATORS,
        )
        docs: List[Document] = []
        for md_file in sorted(DOCS_DIR.glob("*.md")):
            source = md_file.stem
            text = md_file.read_text(encoding="utf-8")
            # Split on lines starting with "## " to extract named sections
            sections = re.split(r"\n(?=## )", text)
            for section in sections:
                lines = section.strip().splitlines()
                if not lines:
                    continue
                heading = lines[0].lstrip("# ").strip()
                body = "\n".join(lines[1:]).strip()
                if not body:
                    continue
                chunks = splitter.create_documents(
                    [body],
                    metadatas=[{"source": source, "section": heading}],
                )
                docs.extend(chunks)
        return docs

    # ── Retrieval ─────────────────────────────────────────────────────────────

    async def aretrieve(self, query: str, k: int = 3) -> List[Document]:
        """
        Async hybrid retrieval — safe to call from FastAPI handlers.
        Returns at most k de-duplicated chunks ranked by RRF score.
        """
        await self._ensure_initialized()
        assert self._retriever is not None
        results = await self._retriever.ainvoke(query)
        return results[:k]

    def retrieve(self, query: str, k: int = 3) -> List[Document]:
        """
        Synchronous retrieval — used inside LangChain @tool functions where
        an event loop may already be running.
        """
        if not self._initialized:
            self._sync_init()
        assert self._retriever is not None
        results = self._retriever.invoke(query)
        return results[:k]

    # ── Formatting ────────────────────────────────────────────────────────────

    @staticmethod
    def format_context(docs: List[Document]) -> str:
        """
        Render retrieved chunks as a labeled context block for injection into
        the agent system prompt.

        Example output:
            [medical_knowledge · 高血压（Hypertension）]
            高血压是指动脉血压持续升高…

            ---

            [lab_reference · 血常规参考范围]
            红细胞计数（RBC）…
        """
        if not docs:
            return ""
        parts: List[str] = []
        for doc in docs:
            src = doc.metadata.get("source", "")
            sec = doc.metadata.get("section", "")
            label = f"[{src} · {sec}]" if sec else f"[{src}]"
            parts.append(f"{label}\n{doc.page_content}")
        return "\n\n---\n\n".join(parts)


@lru_cache(maxsize=1)
def get_knowledge_base() -> HealthKnowledgeBase:
    """Singleton accessor — returns the same instance for the process lifetime."""
    return HealthKnowledgeBase()
