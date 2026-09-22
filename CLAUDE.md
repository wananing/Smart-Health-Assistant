# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Smart Health Assistant (大健康智能助手) — a mobile-first, Chinese-language healthcare AI platform. A FastAPI + LangGraph backend routes each user turn to a specialist agent (clinic triage, insurance, lab-report interpretation, pharmacy, general advisor) and streams the reply over SSE, including structured UI card events that the React frontend renders. `AGENTS.md` at the repo root holds the team's contribution conventions (commit style, PR expectations, privacy rules) and applies alongside this file.

## Development Commands

### Backend (`backend/`, Python ≥3.13, managed with `uv`)

```bash
cd backend
uv sync                                          # install deps from uv.lock
cp .env.example .env                             # then set LLM_PROVIDER + the matching API key
uv run python -m rag.ingest                      # first run: build the RAG vector store (~90MB model download)
uv run python -m rag.ingest --rebuild            # after editing rag/documents/*.md
uv run uvicorn main:app --reload --port 8000     # dev server
```

Tests are split into two kinds. Keep them separate when running or adding tests:

```bash
# Deterministic unit tests (unittest, no network, no API key). pytest also works.
uv run python -m unittest test_llm.py test_vision.py test_main_config.py test_observability.py test_evals.py
uv run python -m unittest test_llm.py                                  # one file
uv run python -m unittest test_llm.ModelSettingsTests.test_legacy_ark_configuration_remains_the_default  # one test

# Manual scripts that call the configured LLM (need a real API key in .env; run explicitly, never in CI)
uv run python test_router.py        # router prompt classification check
uv run python test_clinic.py        # streams a clinic turn end-to-end
uv run python test_exit_phrases.py  # exit-phrase routing
uv run python test_clinic_issue.py
```

Regression evals (also call the LLM; non-zero exit on any failure):

```bash
uv run python -m evals                              # all cases in evals/cases.jsonl, local strict scoring
uv run python -m evals --case route-report-lab      # one case by id
uv run --extra eval python -m evals --provider deepeval   # optional DeepEval tool scoring
```

### Frontend (`frontend/`, React 19 + Vite + Tailwind, TypeScript strict)

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173
npm run lint     # ESLint
npm run build    # tsc -b + vite build (this is the type check)
node test_pw.cjs # Playwright smoke script; needs the dev server already running on :5173
```

`test_pw.cjs`, `test_console.cjs`, `test_debug.cjs`, `test_review.cjs` are plain Node scripts, not a Playwright test runner suite. The UI targets a phone viewport; verify changes with iPhone 13 emulation in Chrome DevTools.

### Local tracing (optional)

```bash
docker compose -f compose.observability.yml up -d   # Jaeger UI on http://localhost:16686, OTLP on :4318
# then in backend/.env: OBSERVABILITY_PROVIDER=otel
```

## Architecture

### Request lifecycle (the part that spans several files)

The graph is **stateless per request**. There is no checkpointer. The frontend sends the full message history plus a `chat_mode` on every call, and the backend derives everything from that:

1. `POST /api/chat` (`backend/main.py`) maps `chat_mode` → `active_agent` via `_MODE_TO_AGENT`, keeps the last 10 messages, and builds `MainAgentState` (`agents/state.py`: `messages`, `user_info`, `next_agent`, `active_agent`).
2. `router_node` (`agents/router.py`): if the text contains an exit phrase (退出/结束/不看了/取消…) it resets to `advisor_agent`; else if `active_agent` is already a specialist it short-circuits without calling the LLM; else it runs a temperature-0 classifier and matches the agent id by substring.
3. `agents/graph.py` wires `START → router → <one specialist node> → END`. `master_app` is compiled at import time; `main.py` imports it lazily on first request.
4. Each specialist node builds a `create_react_agent` on the fly with its tools and skills, injects user info (and RAG context for clinic/report/advisor) into the system prompt, runs it, and returns only the newly appended messages.
5. `_stream_agent_events` in `main.py` translates `astream_events(version="v2")` into SSE events: `text`, `node_start`/`node_end` (only for nodes listed in `_NODE_LABELS`), `tool_start`/`tool_end` (labels from `_SKILL_LABELS`), `card`, `finish`, `error`.
6. The frontend (`services/chatService.ts`) flips `chatMode` when it sees a `node_start` for a specialist node (`NODE_TO_CHAT_MODE`), which is how "mode lock" persists across turns: the next request carries the new `chat_mode`. An `advisor_node` start signals exit back to `general`.

`POST /api/vision-chat` (multipart: `file`, `scan_type` ∈ `report|drug_box|trace_code`, JSON-string `user_info`/`messages`) runs `agents/vision.py` first: validates MIME/size (JPEG/PNG/WebP, ≤8MB), calls the vision model, redacts PII from the result, wraps it as a *user* message (never a system prompt), then feeds the same `_stream_agent_events` pipeline with `active_agent` forced to report or pharmacy. It emits a `tool_start`/`tool_end` for `vision_model` before the graph events.

### Cards: backend tool → frontend component

A `card` SSE event is emitted in `main.py` on `on_tool_end` when the tool name appears in a mapping. The mappings are three dicts in two files:

- `main.py`: `_INSURANCE_TOOL_TO_CARD_TYPE` (4 insurance tools) and `_REPORT_TOOL_TO_CARD_TYPE` (`lab_interpreter` → `report_analysis`)
- `agents/pharmacy.py`: `PHARMACY_TOOL_TO_CARD_TYPE` (`search_drug_info` → `medication_task`, `find_nearby_pharmacy` → `hospital_list`)

The tool's return value must be a JSON string; it becomes `payload.data`. Some `ChatCardPayload` variants (`mode_welcome`, `mode_exit`, `sensitive_image_preview`, `clinic_recommendation`) are created frontend-side only. To add a backend-driven card: return JSON from the tool, add the tool → type mapping, add the variant to `ChatCardPayload` in `frontend/src/types/index.ts`, add a `case` in `components/chat/ChatCardRenderer.tsx`. Add a display label in `_SKILL_LABELS` too or the status bubble shows a raw tool name.

### Model configuration (`agents/llm.py`)

All providers are OpenAI-compatible and selected by `LLM_PROVIDER` (`ark` default, `openai`, `deepseek`, `qwen`, `zhipu`, `custom`; aliases like `doubao`, `dashscope`, `glm` resolve to these). Each provider has its own key/model/base-url env names; `LLM_API_KEY`/`LLM_MODEL`/`LLM_BASE_URL` override any provider. Vision resolves separately with `purpose="vision"`: `VISION_PROVIDER`/`VISION_API_KEY`/`VISION_MODEL`/`VISION_BASE_URL` first, then the chat settings. `resolve_model_settings()` validates without a network call and is what `test_llm.py` exercises; `get_chat_llm(preset)` returns a `ChatOpenAI` with temperature presets `router`=0.0, `precise`=0.2, `balanced`=0.4, `fast`=0.7. ARK adds `extra_body={"thinking": {"type": "disabled"}}`.

### Frontend state

`store/GlobalContext.tsx` (`useGlobalStore`) owns `chatMode`, `messages`, `isElderMode`, scanner state, and `enterChatMode()`/`exitChatMode()`, which insert the `mode_welcome`/`mode_exit` cards. `screens/` are full-page views per mode; `HomeScreen` hosts the chat (`GlobalChatView` → `AgentStatusBubble` + `ChatCardRenderer`, `InputBar`). The backend URL `http://localhost:8000` is hardcoded in `chatService.ts`; backend CORS allows only `localhost:5173` and `5174`.

### RAG (`backend/rag/`)

`HealthKnowledgeBase` (singleton via `get_knowledge_base()`) is a hybrid retriever: BM25 (30%) + dense MMR (70%) fused with RRF over the Markdown files in `rag/documents/` (medical knowledge, insurance policies, lab reference, pharmacy knowledge; chunked by `## ` headers). Embedding provider (`EMBEDDING_PROVIDER`: huggingface default / openai / ark) and vector store (`VECTOR_STORE`: chroma default / faiss / qdrant / pgvector) are env-selected factories in `embeddings.py` and `vectorstores.py`. Clinic, report, and advisor nodes call `aretrieve`/`amulti_query_retrieve` and inject results into the system prompt; the insurance agent exposes retrieval as the `search_insurance_policy` tool. The store directory is gitignored; rebuild after changing documents. Details: `docs/rag.md`.

### Skills (`backend/skills/`)

Custom registry (LangGraph has no native skill concept): each `skills/<name>/` has a `SKILL.md` with YAML frontmatter (`name`, `description`, `tags`, `version`) plus a `skill.py` subclassing `BaseSkill`. The registry auto-discovers on startup and wraps each as a `@tool`; agents call `get_agent_tools(tags=["clinic"])` and also get `load_skill`, a universal tool that can invoke any registered skill by name. Every output extends `SkillOutput` (`skill_name`, `success`, `confidence`, `disclaimer` — the agent must surface the disclaimer). Tag → node: `clinic`, `advisor`, `report`, `pharmacy`. The `name`/`tags` in `skill.py` must match `SKILL.md`. Full how-to: `docs/skills.md`.

### Observability and evals

`observability.py` picks `OBSERVABILITY_PROVIDER` (`none` default, `otel` via OpenInference → OTLP, `langsmith`). `TRACE_CONTENT` and `TRACE_IMAGES` both default to false; inputs are only recorded when both are true, so medical text and images stay out of spans unless opted in. `evals/cases.jsonl` holds anonymous routing/tool-selection cases (`id`, `input`, `expected_agent`, optional `expected_tools`, `chat_mode`); case ids must be machine-safe with no personal names (enforced in `evals/__init__.py`). When adding an agent capability, add at least one happy-path and one safety-boundary case. Details: `docs/observability-evals.md`.

## Adding a New Agent

1. Create `backend/agents/<name>.py` with an async `<name>_node(state)` that returns `{"messages": new_messages}`.
2. Register the node and its edge in `agents/graph.py` (`_AGENT_MAP` + `add_node`/`add_conditional_edges`/`add_edge`).
3. Add it to the classifier prompt and substring matching in `agents/router.py`, to `_MODE_TO_AGENT` and `_NODE_LABELS` in `main.py`, and to `MODE_TO_AGENT` in `evals/run.py`.
4. Frontend: add the `ChatMode` variant in `types/index.ts`, the node → mode entry in `chatService.ts` `NODE_TO_CHAT_MODE`, a screen under `screens/`, and register it in `App.tsx`.
5. Optionally tag skills for it and call `get_agent_tools(tags=["<name>"])` in the node.

## Privacy constraints (from AGENTS.md and the vision design doc)

Never log raw images, base64 payloads, full model output, or personal health information from the backend. Vision-model output is untrusted user material and must be redacted (`redact_sensitive_text`) and passed as a user message. Keep `TRACE_CONTENT`/`TRACE_IMAGES` off by default and use only synthetic or anonymized samples in tests and evals.
