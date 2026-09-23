"""
Checkpointer factory for the master LangGraph application.

A checkpointer gives the graph server-side memory: every super-step is
persisted under a ``thread_id`` so the next request only has to send the new
user message, and so ``interrupt()`` based follow-up questions can be resumed.

Backends (selected with the ``CHECKPOINTER`` environment variable):
  memory (default) — ``MemorySaver``; per-process, lost on restart
  sqlite           — ``AsyncSqliteSaver`` persisted at ``CHECKPOINT_DB_PATH``
"""
from __future__ import annotations

import asyncio
import os

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver

DEFAULT_CHECKPOINT_DB_PATH = "checkpoints.sqlite"
_BACKEND_ALIASES = {
    "": "memory",
    "memory": "memory",
    "inmemory": "memory",
    "in-memory": "memory",
    "memorysaver": "memory",
    "sqlite": "sqlite",
    "aiosqlite": "sqlite",
}


class CheckpointerConfigurationError(ValueError):
    """Raised when the checkpointer environment variables are unusable."""


def resolve_checkpointer_backend(env: dict[str, str] | None = None) -> str:
    """Normalize ``CHECKPOINTER`` into one of ``memory`` / ``sqlite``."""
    values = os.environ if env is None else env
    raw = values.get("CHECKPOINTER", "").strip().lower().replace("_", "")
    backend = _BACKEND_ALIASES.get(raw)
    if backend is None:
        supported = "memory, sqlite"
        raise CheckpointerConfigurationError(
            f"Unsupported CHECKPOINTER '{raw}'. Supported backends: {supported}"
        )
    return backend


def resolve_checkpoint_db_path(env: dict[str, str] | None = None) -> str:
    """Return the SQLite file path used by the ``sqlite`` backend."""
    values = os.environ if env is None else env
    return values.get("CHECKPOINT_DB_PATH", "").strip() or DEFAULT_CHECKPOINT_DB_PATH


def create_checkpointer(env: dict[str, str] | None = None) -> BaseCheckpointSaver:
    """Build the checkpointer selected by the environment."""
    backend = resolve_checkpointer_backend(env)
    if backend == "memory":
        return MemorySaver()

    try:
        asyncio.get_running_loop()
    except RuntimeError as exc:  # pragma: no cover - depends on import context
        raise CheckpointerConfigurationError(
            "CHECKPOINTER=sqlite needs an active event loop; build the graph "
            "from the running server (uvicorn) or use CHECKPOINTER=memory."
        ) from exc

    import aiosqlite
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    db_path = resolve_checkpoint_db_path(env)
    connection = aiosqlite.connect(db_path, check_same_thread=False)
    connection.daemon = True
    return AsyncSqliteSaver(connection)
