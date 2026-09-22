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

# Regenerate the graph diagram after changing the graph shape
uv run python -c "from agents.graph import master_app; print(master_app.get_graph(xray=1).draw_mermaid())" > ../docs/images/graph.mmd
```

Server-side conversation memory is on by default (`CHECKPOINTER=memory`). Set `CHECKPOINTER=sqlite` (+ optional `CHECKPOINT_DB_PATH`, default `checkpoints.sqlite`, gitignored) to survive restarts. Details: `docs/langgraph-runtime.md`.

Tests are split into two kinds. Keep them separate when running or adding tests:

```bash
# Deterministic unit tests (unittest, no network, no API key). pytest also works.
uv run python -m unittest test_llm.py test_vision.py test_main_config.py test_observability.py test_evals.py
uv run python -m unittest test_clinic_graph.py test_graph_build.py   # clinic subgraph + checkpointer wiring
uv run python -m unittest test_handoff.py test_cards.py                # Command handoffs + agent-emitted cards
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

The master graph is compiled **with a checkpointer** (`agents/checkpointing.py`), so conversations can be continued server-side by `thread_id`. The frontend still sends `chat_mode` on every call:

1. `POST /api/chat` (`backend/main.py`) maps `chat_mode` → `active_agent` via `_MODE_TO_AGENT` and builds `MainAgentState` (`agents/state.py`: `messages`, `user_info`, `next_agent`, `active_agent`, `handoff_count`). The request may carry an optional `thread_id`; the stream always opens with a `{"type": "session", "thread_id": …}` event. `_resolve_graph_input` then picks the input: a pending `interrupt` on that thread → `Command(resume=<user text>)`; a known thread → only the newest message (the checkpointer holds the history); an unknown or absent thread → the full history from the request (backward compatible).
2. `router_node` (`agents/router.py`): if the message **is** an exit phrase (退出/结束/不看了/取消…) or **starts** with one followed by punctuation, it resets to `advisor_agent` — `is_exit_request()` is anchored, so 我想取消明天的预约 no longer exits; else if `active_agent` is already a specialist it short-circuits without calling the LLM; else it runs a temperature-0 classifier and matches the agent id by substring. Every return path resets `handoff_count` to 0, which is what makes the handoff budget per-turn.
3. `agents/graph.py` wires `START → router → <one specialist node> → END`, and registers every specialist with `destinations=` so the **handoff** edges between them render in `get_graph()`. `master_app` is compiled at import time; `main.py` imports it lazily on first request.
4. `insurance_node`, `report_node`, `pharmacy_node`, `advisor_node` each build a `create_react_agent` on the fly with their tools and skills, inject user info (and RAG context) into the system prompt, run it, and return only the newly appended messages. `clinic_node` is different: it is a **compiled subgraph** (`agents/clinic.py`) with its own `ClinicState` — a code-level `emergency_gate` (pure rule matching, no LLM), structured symptom extraction, a deterministic sufficiency check, `interrupt()`-based follow-up questions, and a `conclude` node that streams a `clinic_recommendation` card. It still returns `{"messages": new_messages}` to the parent. Any of the five may instead return a `Command(goto=…)` **handoff** — see below. See `docs/langgraph-runtime.md`.
5. `_stream_agent_events` in `main.py` translates `astream_events(version="v2", stream_mode=["updates", "custom"], subgraphs=True)` into SSE events: `text`, `node_start`/`node_end` (only for nodes listed in `_NODE_LABELS`), `tool_start`/`tool_end` (labels from `_SKILL_LABELS`), `card`, `finish`, `error`, plus `session` and `interrupt`. Root-level `custom` chunks pushed by an agent via `agents/streaming.py` are forwarded verbatim when their `type` is `card` or `text` (`_STREAMABLE_CUSTOM_TYPES` is the only gate); `__interrupt__` updates are surfaced as a `text` event carrying the follow-up question followed by an `interrupt` marker.
6. The frontend (`services/chatService.ts`) flips `chatMode` when it sees a `node_start` for a specialist node (`NODE_TO_CHAT_MODE`), which is how "mode lock" persists across turns: the next request carries the new `chat_mode`. An `advisor_node` start signals exit back to `general`. A mid-turn handoff needs no frontend code: the target node's own `node_start` flips the mode.

`POST /api/vision-chat` (multipart: `file`, `scan_type` ∈ `report|drug_box|trace_code`, JSON-string `user_info`/`messages`) runs `agents/vision.py` first: validates MIME/size (JPEG/PNG/WebP, ≤8MB), calls the vision model, redacts PII from the result, wraps it as a *user* message (never a system prompt), then feeds the same `_stream_agent_events` pipeline with `active_agent` forced to report or pharmacy. It emits a `tool_start`/`tool_end` for `vision_model` before the graph events.

### Handoffs: escaping the mode lock (`agents/handoff.py`)

`active_agent` locks the conversation into a specialist, so an insurance-mode user asking about a symptom used to get an insurance answer until they typed an exit phrase. Handoffs fix that.

Each specialist's ReAct agent carries `transfer_to_clinic` / `transfer_to_insurance` / `transfer_to_report` / `transfer_to_pharmacy` / `transfer_to_advisor` for the *other* four (`get_handoff_tools(AGENT_ID)`), plus the `handoff_prompt_section(AGENT_ID)` paragraph appended to its system prompt.

Four of the five agents run their ReAct agent with `create_react_agent(...).ainvoke(...)` **inside** a node function, so a `Command` raised in a tool can never reach the master graph. The pattern instead:

1. The tool returns a JSON `ToolMessage`: `{"handoff": "<agent_id>", "reason": …}`.
2. After `ainvoke`, the node calls `apply_handoff(state, new_messages)`. `split_handoff()` finds the payload and drops **the `AIMessage` that requested it and everything after it**, so no orphaned `tool_calls` reach the history and the target sees the user's own message last.
3. On a hit the node returns `Command(goto="<target>_node", update={"messages": kept, "active_agent", "next_agent", "handoff_count": n+1})`; the target handles the *same* user turn. Otherwise it returns `{"messages": new_messages}` as before.

`clinic_node` is a mounted subgraph, so its `conclude` node uses `apply_handoff(..., parent=True)` → `Command(graph=Command.PARENT, goto=…)`. `ClinicState` mirrors `handoff_count` so the budget is respected inside the subgraph too.

`MAX_HANDOFFS_PER_TURN = 1`: a second handoff in the same turn is logged and ignored (the agent's own reply is kept instead), and `router_node` resets `handoff_count` on every turn. A `Command(goto=…)` overrides the static `node → END` edge for that run.

### Cards: emitted by the agent, not sniffed in `main.py`

Since v2.1.0 `main.py` knows **nothing** about tool names for card purposes — there are no tool→card-type dicts. Every card-producing tool pushes its own already-shaped SSE payload through `agents/streaming.py` (`emit_card(card_type, data)` → `get_stream_writer()`), and `_stream_agent_events` forwards it from the `custom` stream. Verified: a `get_stream_writer()` write from inside a tool run by a ReAct agent nested in a node *does* surface on the root `astream_events(..., subgraphs=True)` stream, and it lands after `tool_end` and before the final summary text — the same order as the old `on_tool_end` branch.

Who emits what:

- `agents/insurance.py` — `get_insurance_balance` → `insurance_balance`, `get_consumption_records` → `insurance_expenses`, `get_payment_records` → `insurance_payments`, `get_cross_region_info` → `insurance_cross_region`
- `agents/pharmacy.py` — `search_drug_info` → `medication_task`, `find_nearby_pharmacy` → `hospital_list`
- `agents/report.py` — `report_node._emit_report_cards()` replays the turn's `lab_interpreter` `ToolMessage`s as `report_analysis`. Node level, not tool level, because that skill is generic and shared with the clinic line; this card therefore arrives *after* the summary text
- `agents/clinic.py` — `clinic_recommendation` from `conclude` and from the CRITICAL branch of `emergency_gate`

`mode_welcome`, `mode_exit` and `sensitive_image_preview` are created frontend-side only. To add a backend-driven card: build the dict, call `emit_card("my_type", data)` in the tool (or in the node, if the tool is shared), add the variant to `ChatCardPayload` in `frontend/src/types/index.ts`, add a `case` in `components/chat/ChatCardRenderer.tsx`. Add a display label in `_SKILL_LABELS` too or the status bubble shows a raw tool name.

### Model configuration (`agents/llm.py`)

All providers are OpenAI-compatible and selected by `LLM_PROVIDER` (`ark` default, `openai`, `deepseek`, `qwen`, `zhipu`, `custom`; aliases like `doubao`, `dashscope`, `glm` resolve to these). Each provider has its own key/model/base-url env names; `LLM_API_KEY`/`LLM_MODEL`/`LLM_BASE_URL` override any provider. Vision resolves separately with `purpose="vision"`: `VISION_PROVIDER`/`VISION_API_KEY`/`VISION_MODEL`/`VISION_BASE_URL` first, then the chat settings. `resolve_model_settings()` validates without a network call and is what `test_llm.py` exercises; `get_chat_llm(preset)` returns a `ChatOpenAI` with temperature presets `router`=0.0, `precise`=0.2, `balanced`=0.4, `fast`=0.7. ARK adds `extra_body={"thinking": {"type": "disabled"}}`.

### Frontend state

`store/GlobalContext.tsx` (`useGlobalStore`) owns `chatMode`, `messages`, `isElderMode`, scanner state, `threadId`, and `enterChatMode()`/`exitChatMode()`, which insert the `mode_welcome`/`mode_exit` cards. `threadId` is adopted from the backend `session` event; while it is set, `chatService.ts` sends only the newest message. `exitChatMode()` (and `resetThread()`) clears it, starting a fresh server-side conversation. `screens/` are full-page views per mode; `HomeScreen` hosts the chat (`GlobalChatView` → `AgentStatusBubble` + `ChatCardRenderer`, `InputBar`). The backend URL `http://localhost:8000` is hardcoded in `chatService.ts`; backend CORS allows only `localhost:5173` and `5174`.

### RAG (`backend/rag/`)

`HealthKnowledgeBase` (singleton via `get_knowledge_base()`) is a hybrid retriever: BM25 (30%) + dense MMR (70%) fused with RRF over the Markdown files in `rag/documents/` (medical knowledge, insurance policies, lab reference, pharmacy knowledge; chunked by `## ` headers). Embedding provider (`EMBEDDING_PROVIDER`: huggingface default / openai / ark) and vector store (`VECTOR_STORE`: chroma default / faiss / qdrant / pgvector) are env-selected factories in `embeddings.py` and `vectorstores.py`. Clinic, report, and advisor nodes call `aretrieve`/`amulti_query_retrieve` and inject results into the system prompt; the insurance agent exposes retrieval as the `search_insurance_policy` tool. The store directory is gitignored; rebuild after changing documents. Details: `docs/rag.md`.

### Skills (`backend/skills/`)

Custom registry (LangGraph has no native skill concept): each `skills/<name>/` has a `SKILL.md` with YAML frontmatter (`name`, `description`, `tags`, `version`) plus a `skill.py` subclassing `BaseSkill`. The registry auto-discovers on startup and wraps each as a `@tool`; agents call `get_agent_tools(tags=["clinic"])` and also get `load_skill`, a universal tool that can invoke any registered skill by name. Every output extends `SkillOutput` (`skill_name`, `success`, `confidence`, `disclaimer` — the agent must surface the disclaimer). Tag → node: `clinic`, `advisor`, `report`, `pharmacy`. The `name`/`tags` in `skill.py` must match `SKILL.md`. Full how-to: `docs/skills.md`.

### Observability and evals

`observability.py` picks `OBSERVABILITY_PROVIDER` (`none` default, `otel` via OpenInference → OTLP, `langsmith`). `TRACE_CONTENT` and `TRACE_IMAGES` both default to false; inputs are only recorded when both are true, so medical text and images stay out of spans unless opted in. `evals/cases.jsonl` holds anonymous routing/tool-selection cases (`id`, `input`, `expected_agent`, optional `expected_tools`, `chat_mode`); case ids must be machine-safe with no personal names (enforced in `evals/__init__.py`). When adding an agent capability, add at least one happy-path and one safety-boundary case. Details: `docs/observability-evals.md`.

## Adding a New Agent

1. Create `backend/agents/<name>.py` with an async `<name>_node(state)` returning `{"messages": new_messages}` — or, if it can hand off, `apply_handoff(state, new_messages)`.
2. Register the node and its edge in `agents/graph.py` (`_AGENT_MAP` + `add_node(..., destinations=(*handoff_destinations("<name>_agent"), END))`/`add_conditional_edges`/`add_edge`).
3. Add it to the classifier prompt and substring matching in `agents/router.py`, to `_HANDOFF_SPECS` and `HANDOFF_TOOL_LABELS` in `agents/handoff.py`, to `_MODE_TO_AGENT` and `_NODE_LABELS` in `main.py`, and to `MODE_TO_AGENT` in `evals/run.py`.
4. Frontend: add the `ChatMode` variant in `types/index.ts`, the node → mode entry in `chatService.ts` `NODE_TO_CHAT_MODE`, a screen under `screens/`, and register it in `App.tsx`.
5. Optionally tag skills for it and call `get_agent_tools(tags=["<name>"])` in the node.
6. If it produces cards, call `emit_card(...)` from `agents/streaming.py` inside its tools — never add tool-name sniffing back to `main.py`.

## Privacy constraints (from AGENTS.md and the vision design doc)

Never log raw images, base64 payloads, full model output, or personal health information from the backend. Vision-model output is untrusted user material and must be redacted (`redact_sensitive_text`) and passed as a user message. Keep `TRACE_CONTENT`/`TRACE_IMAGES` off by default and use only synthetic or anonymized samples in tests and evals.
