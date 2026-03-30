"""
Vector store factory.

Configured via the VECTOR_STORE env var:
  chroma    (default) — file-based, no server needed
  faiss               — in-memory + local disk, fast
  qdrant              — production-grade, requires Qdrant server
  pgvector            — PostgreSQL extension, requires PGVECTOR_CONNECTION_STRING

Pass rebuild=True to drop and rebuild the store from documents.
"""
import os
from pathlib import Path
from typing import List, Optional

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import VectorStore

_CHROMA_DEFAULT_DIR = str(Path(__file__).parent / "chroma_db")
_FAISS_DEFAULT_PATH = str(Path(__file__).parent / "faiss_index")


def get_vectorstore(
    embeddings: Embeddings,
    documents: Optional[List[Document]] = None,
    *,
    rebuild: bool = False,
) -> VectorStore:
    """
    Return a VectorStore instance for the configured backend.

    If the store does not exist yet (or rebuild=True), it is built from `documents`.
    `documents` must be provided when building a new store.
    """
    backend = os.getenv("VECTOR_STORE", "chroma").lower()

    if backend == "faiss":
        return _get_faiss(embeddings, documents, rebuild=rebuild)
    elif backend == "qdrant":
        return _get_qdrant(embeddings, documents, rebuild=rebuild)
    elif backend == "pgvector":
        return _get_pgvector(embeddings, documents, rebuild=rebuild)
    else:
        return _get_chroma(embeddings, documents, rebuild=rebuild)


# ── Chroma ────────────────────────────────────────────────────────────────────

def _get_chroma(
    embeddings: Embeddings,
    documents: Optional[List[Document]],
    rebuild: bool,
) -> VectorStore:
    from langchain_chroma import Chroma

    persist_dir = os.getenv("CHROMA_PERSIST_DIR", _CHROMA_DEFAULT_DIR)
    Path(persist_dir).mkdir(parents=True, exist_ok=True)

    existing_db = Path(persist_dir) / "chroma.sqlite3"
    if existing_db.exists() and not rebuild:
        return Chroma(
            persist_directory=persist_dir,
            embedding_function=embeddings,
            collection_name="health_kb",
        )

    if documents is None:
        raise ValueError("documents must be provided to build a new Chroma store")
    return Chroma.from_documents(
        documents=documents,
        embedding=embeddings,
        persist_directory=persist_dir,
        collection_name="health_kb",
    )


# ── FAISS ─────────────────────────────────────────────────────────────────────

def _get_faiss(
    embeddings: Embeddings,
    documents: Optional[List[Document]],
    rebuild: bool,
) -> VectorStore:
    from langchain_community.vectorstores import FAISS

    index_path = os.getenv("FAISS_INDEX_PATH", _FAISS_DEFAULT_PATH)
    if Path(index_path).exists() and not rebuild:
        return FAISS.load_local(
            index_path, embeddings, allow_dangerous_deserialization=True
        )

    if documents is None:
        raise ValueError("documents must be provided to build a new FAISS index")
    store = FAISS.from_documents(documents, embeddings)
    store.save_local(index_path)
    return store


# ── Qdrant ────────────────────────────────────────────────────────────────────

def _get_qdrant(
    embeddings: Embeddings,
    documents: Optional[List[Document]],
    rebuild: bool,
) -> VectorStore:
    from langchain_qdrant import QdrantVectorStore
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, VectorParams

    url = os.getenv("QDRANT_URL", "http://localhost:6333")
    api_key = os.getenv("QDRANT_API_KEY") or None
    collection = "health_kb"

    client = QdrantClient(url=url, api_key=api_key)
    existing = [c.name for c in client.get_collections().collections]

    if collection in existing and not rebuild:
        return QdrantVectorStore(
            client=client, collection_name=collection, embedding=embeddings
        )

    if collection in existing:
        client.delete_collection(collection)

    if documents is None:
        raise ValueError("documents must be provided to build a new Qdrant collection")

    # Infer vector dimension from a test embed
    sample_vec = embeddings.embed_query("test")
    client.create_collection(
        collection_name=collection,
        vectors_config=VectorParams(size=len(sample_vec), distance=Distance.COSINE),
    )
    store = QdrantVectorStore(
        client=client, collection_name=collection, embedding=embeddings
    )
    store.add_documents(documents)
    return store


# ── pgvector ──────────────────────────────────────────────────────────────────

def _get_pgvector(
    embeddings: Embeddings,
    documents: Optional[List[Document]],
    rebuild: bool,
) -> VectorStore:
    from langchain_postgres import PGVector

    conn_str = os.getenv("PGVECTOR_CONNECTION_STRING")
    if not conn_str:
        raise ValueError(
            "PGVECTOR_CONNECTION_STRING env var is required for the pgvector backend"
        )

    store = PGVector(
        embeddings=embeddings,
        collection_name="health_kb",
        connection=conn_str,
        pre_delete_collection=rebuild,
    )
    if documents and rebuild:
        store.add_documents(documents)
    return store
