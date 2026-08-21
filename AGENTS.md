# Repository Guidelines

## Project Structure & Module Organization

This project pairs a FastAPI/LangGraph backend with a React/Vite frontend. Backend lives in `backend/`: `main.py` exposes API/SSE endpoints, `agents/` contains specialists, `skills/` contains tools, `rag/` contains retrieval code, and `evals/` contains regression cases. Tests and manual checks are `backend/test_*.py` files.

Frontend source is in `frontend/src/`: views use `screens/`, reusable UI uses `components/`, and shared state, clients, and contracts use `store/`, `services/`, and `types/`. Assets belong in `frontend/public/` or `frontend/src/assets/`; documentation lives in the three `docs/` directories.

## Build, Test, and Development Commands

- `cd backend && uv sync`: install Python 3.13 dependencies from `uv.lock`.
- `cd backend && uv run python -m rag.ingest`: build the RAG index; add `--rebuild` after document changes.
- `cd backend && uv run uvicorn main:app --reload --port 8000`: run the API locally.
- `cd backend && uv run python -m unittest test_llm.py test_vision.py test_main_config.py test_observability.py test_evals.py`: run deterministic backend tests.
- `cd frontend && npm install`: install frontend dependencies.
- `cd frontend && npm run dev`: start Vite at `http://localhost:5173`.
- `cd frontend && npm run lint && npm run build`: lint, type-check, and build.
- `cd frontend && node test_pw.cjs`: run the Playwright smoke flow with the app available.

## Coding Style & Naming Conventions

Use 4-space indentation, type hints, and Pydantic models in Python. Name agents by role (`clinic.py`). New skills require `backend/skills/<skill_name>/SKILL.md`, `skill.py`, and `__init__.py`.

Use TypeScript and React function components. Components use PascalCase (`ChatCardRenderer.tsx`); utilities and services use camelCase. Keep SSE payloads synchronized with `frontend/src/types/index.ts`. Follow existing mobile-first styles and run ESLint.

## Testing Guidelines

Add deterministic tests for validation, routing helpers, and transformations. Manual scripts such as `test_router.py` call configured LLMs and require provider credentials such as `ARK_API_KEY` or `OPENAI_API_KEY`; run them explicitly with `uv run python test_router.py`. For UI changes, verify a mobile viewport and extend Playwright coverage where practical.

## Commit & Pull Request Guidelines

Keep commits focused. History mixes Chinese summaries with prefixes such as `docs:` and `refactor:`; prefer `<type>: <area and outcome>`. Pull requests should describe behavior, list verification commands, link issues, and include screenshots or recordings for mobile UI changes.

## Security & Configuration Tips

Never commit `.env`, API keys, virtual environments, frontend build output, or generated stores such as `backend/rag/chroma_db/`. Avoid logging raw medical images or personal health information. Keep frontend service URLs and backend CORS origins aligned with ports `5173` and `8000`.
