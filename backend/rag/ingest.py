"""
Knowledge base ingestion script.

Builds (or rebuilds) the vector store from documents in rag/documents/.
Run this once after setup, and again whenever documents change.

Usage:
    python -m rag.ingest              # build if not exists, skip otherwise
    python -m rag.ingest --rebuild    # force rebuild from documents

Environment variables (read from .env):
    EMBEDDING_PROVIDER  huggingface | openai | ark  (default: huggingface)
    EMBEDDING_MODEL     model name / path            (default: BAAI/bge-small-zh-v1.5)
    VECTOR_STORE        chroma | faiss | qdrant | pgvector  (default: chroma)
    CHROMA_PERSIST_DIR  path for Chroma store        (default: rag/chroma_db)
    FAISS_INDEX_PATH    path for FAISS index         (default: rag/faiss_index)
    QDRANT_URL          Qdrant server URL            (default: http://localhost:6333)
    PGVECTOR_CONNECTION_STRING  PostgreSQL DSN
"""
import argparse
import sys
import time

from dotenv import load_dotenv

load_dotenv()  # load .env before importing rag modules so env vars are available


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the health knowledge base vector store."
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Force rebuild even if the store already exists",
    )
    args = parser.parse_args()

    import os

    print("═" * 46)
    print("  Health Knowledge Base — Ingestion")
    print("═" * 46)
    print(f"  Embedding provider : {os.getenv('EMBEDDING_PROVIDER', 'huggingface')}")
    print(f"  Embedding model    : {os.getenv('EMBEDDING_MODEL', 'BAAI/bge-small-zh-v1.5')}")
    print(f"  Vector store       : {os.getenv('VECTOR_STORE', 'chroma')}")
    print(f"  Mode               : {'REBUILD' if args.rebuild else 'BUILD (skip if exists)'}")
    print()

    from rag.knowledge_base import get_knowledge_base

    kb = get_knowledge_base()
    t0 = time.time()
    try:
        if args.rebuild:
            print("Rebuilding vector store from documents …")
            kb.rebuild()
        else:
            print("Building vector store (first run may download embedding model) …")
            kb._sync_init()
    except Exception as exc:
        print(f"\n[ERROR] {exc}", file=sys.stderr)
        sys.exit(1)

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.1f}s  ✓  Vector store is ready.")


if __name__ == "__main__":
    main()
