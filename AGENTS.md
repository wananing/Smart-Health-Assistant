# Repository Guidelines

## Project Structure & Module Organization

This is a Smart Health Assistant with a Python FastAPI/LangGraph backend and React/Vite frontend. Backend lives in `backend/`: `main.py` is the API/SSE entrypoint, `agents/` contains the router and specialist agents, `skills/` contains auto-discovered tools, and `rag/` contains retrieval code plus knowledge documents in `rag/documents/`. Backend `test_*.py` files sit at its root.

Frontend lives in `frontend/src/`: `screens/` are app views, `components/` contains domain UI, `store/` holds shared context, `services/` contains API clients, and `types/` defines shared contracts. Assets are in `frontend/public/` and `frontend/src/assets/`. Docs are under `docs/`, `backend/docs/`, and `frontend/docs/`.

## Build, Test, and Development Commands

- `cd backend && uv sync`: install Python 3.13 dependencies.
- `cd backend && uv run python -m rag.ingest`: build the local RAG index; add `--rebuild` after document edits.
- `cd backend && uv run uvicorn main:app --reload --port 8000`: start the API.
- `cd backend && python -m pytest test_*.py`: run pytest-compatible backend tests.
- `cd frontend && npm install`: install dependencies.
- `cd frontend && npm run dev`: start Vite on `http://localhost:5173`.
- `cd frontend && npm run build`: type-check and build assets.
- `cd frontend && npm run lint`: run ESLint.
- `cd frontend && node test_pw.cjs`: run the Playwright smoke check.

## Coding Style & Naming Conventions

Use 4-space indentation and type hints for Python. Keep agent modules named by role, such as `clinic.py` or `pharmacy.py`. Add skills as `backend/skills/<skill_name>/SKILL.md`, `skill.py`, and `__init__.py`. Use Pydantic models for schemas.

Use TypeScript, React function components, and PascalCase filenames such as `ChatCardRenderer.tsx`. Keep shared types in `frontend/src/types/index.ts`, domain UI in matching component folders, and Tailwind/CSS aligned with the mobile-first design.

## Testing Guidelines

Backend tests may require `.env` values such as `ARK_API_KEY`. Prefer pytest-compatible `test_*.py` files for deterministic logic, and keep manual async checks executable with `python test_name.py`. For frontend changes, run `npm run lint` and `npm run build`; add Playwright checks for UI flow changes.

## Commit & Pull Request Guidelines

Recent history uses prefixes like `docs:`, `refactor:`, and `fix`, with occasional Chinese summaries. Keep commits focused and name the area. Pull requests should include the change, commands run, linked issues, and screenshots or recordings for visible mobile UI changes.

## Security & Configuration Tips

Do not commit `.env`, API keys, generated vector stores such as `backend/rag/chroma_db/`, virtual environments, or frontend build output. Keep CORS and service URLs aligned with local dev ports.
