"""
Embedding provider factory.

Configured via the EMBEDDING_PROVIDER env var:
  huggingface  (default) — BAAI/bge-small-zh-v1.5, local, ~90 MB, no API key
  openai                 — text-embedding-3-small via OpenAI API
  ark                    — ByteDance ARK embedding endpoint (reuses ARK_API_KEY)

Override the model with EMBEDDING_MODEL.
"""
import os

from langchain_core.embeddings import Embeddings


def get_embeddings() -> Embeddings:
    provider = os.getenv("EMBEDDING_PROVIDER", "huggingface").lower()
    model = os.getenv("EMBEDDING_MODEL", "")

    if provider == "openai":
        from langchain_openai import OpenAIEmbeddings

        return OpenAIEmbeddings(model=model or "text-embedding-3-small")

    elif provider == "ark":
        from langchain_openai import OpenAIEmbeddings

        ark_model = model or "doubao-embedding-large-text-240915"
        return OpenAIEmbeddings(
            model=ark_model,
            base_url="https://ark.cn-beijing.volces.com/api/v3",
            api_key=os.getenv("ARK_API_KEY"),
        )

    else:  # huggingface (default)
        from langchain_huggingface import HuggingFaceEmbeddings

        hf_model = model or "BAAI/bge-small-zh-v1.5"
        return HuggingFaceEmbeddings(
            model_name=hf_model,
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )
