"""
Graph-run lifecycle of one voice call: start, progress watchdog, cancel,
buffered input, completion and recovery.

Contract with the call (``gateway.VoiceCall``):

* At most one run per call. A run belongs to the ``TurnTrace`` that started it
  (``Run.trace``); its events reach the call's inbox tagged with
  ``Run.token`` and only the current run's tokens are accepted
  (``is_current``) — events of a run that was cancelled or completed are
  ignored without the call tracking them.
* Speaking is not the run's business. Turn ids for audio are owned by the
  speaker, which never reuses a stopped one (``arbiter.Speaker``).
* User turns committed while a run is busy are *buffered* here and must be
  fed as the next run whatever happens to the current one (completion,
  error, stall, deadline): committed speech is never dropped.
* Two ways to end a run early:
    ``cancel()``  watchdog (stall / hard cap) or a deliberate hang-up. The
                  run is stopped and ``abandon_run`` closes out its pending
                  step while keeping the turn's Q&A (see
                  ``main._abandon_pending_run``).
    ``detach()``  the socket dropped. The run keeps going in the background
                  so its result lands in the checkpoint, bounded by what is
                  left of ``graph_max``; a reconnect on the same thread
                  waits for it (``wait_detached``) before reading the
                  checkpoint. A detached run that hits the cap is cancelled
                  and closed out like a watchdog cancel; no task is leaked.
"""
from __future__ import annotations

import asyncio
import itertools
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from voice.render import LeadCutter, RunOutcome
from voice.turns import TurnTrace, VoiceTimings

if TYPE_CHECKING:  # pragma: no cover
    from voice.gateway import GraphBridge

# Custom-stream types the voice channel understands on top of card/text.
VOICE_CUSTOM_TYPES = frozenset({"card", "text", "facts"})

# Runs still finishing after their socket dropped, by thread id. Holding the
# task here keeps it alive; it removes itself when done.
DETACHED_RUNS: dict[str, asyncio.Task] = {}


async def wait_detached(thread_id: str) -> bool:
    """Wait (bounded by that run's own cap) for a detached run on this thread."""
    task = DETACHED_RUNS.get(thread_id)
    if task is None:
        return False
    await asyncio.gather(asyncio.shield(task), return_exceptions=True)
    return True


@dataclass
class Run:
    token: int
    trace: TurnTrace
    started_at: float
    outcome: RunOutcome = field(default_factory=RunOutcome)
    # The conclusion's first sentence, spoken while the body still streams.
    lead: LeadCutter | None = None
    lead_spoken: bool = False
    task: asyncio.Task | None = None


class RunManager:
    def __init__(
        self,
        *,
        bridge: "GraphBridge",
        timings: VoiceTimings,
        post: Callable[[tuple], Awaitable[None]],
        set_timer: Callable[[str, float], None],
        cancel_timer: Callable[..., None],
    ) -> None:
        self._bridge = bridge
        self._timings = timings
        self._post = post
        self._set_timer = set_timer
        self._cancel_timer = cancel_timer
        self._tokens = itertools.count(1)
        self._detached = False
        self.current: Run | None = None
        self.buffered: list[tuple[str, TurnTrace]] = []

    # --- queries -----------------------------------------------------------
    @property
    def active(self) -> bool:
        return self.current is not None

    def is_current(self, token: int) -> bool:
        return self.current is not None and self.current.token == token

    # --- lifecycle ---------------------------------------------------------
    def start(self, text: str, trace: TurnTrace, *, thread_id: str, user_info: dict) -> Run:
        loop = asyncio.get_running_loop()
        run = Run(token=next(self._tokens), trace=trace, started_at=loop.time())
        self.current = run
        # No-progress watchdog (re-armed by every graph event) + a hard cap.
        self._set_timer("graph_timeout", self._timings.graph_stall)
        self._set_timer("graph_deadline", self._timings.graph_max)
        run.task = asyncio.create_task(self._drive(run, text, thread_id, user_info))
        return run

    def progress(self) -> None:
        if self.current is not None:
            self._set_timer("graph_timeout", self._timings.graph_stall)

    def complete(self, token: int) -> Run | None:
        """The run finished on its own (``graph_done``); hand it back once."""
        if not self.is_current(token):
            return None
        run, self.current = self.current, None
        self._cancel_timer("graph_timeout", "graph_deadline")
        return run

    async def cancel(self, thread_id: str) -> Run | None:
        """Stop the run and close out its pending step, keeping the turn's Q&A."""
        run, self.current = self.current, None
        if run is None:
            return None
        self._cancel_timer("graph_timeout", "graph_deadline")
        if run.task is not None:
            run.task.cancel()
            await asyncio.gather(run.task, return_exceptions=True)
        await self._abandon(thread_id)
        return run

    async def detach(self, thread_id: str) -> None:
        """The socket dropped: let the run finish in the background, bounded."""
        run, self.current = self.current, None
        self._detached = True  # its events no longer go anywhere
        self._cancel_timer("graph_timeout", "graph_deadline")
        if run is None or run.task is None or run.task.done():
            return
        remaining = max(0.0, run.started_at + self._timings.graph_max - asyncio.get_running_loop().time())
        DETACHED_RUNS[thread_id] = asyncio.create_task(
            self._finish_detached(run.task, remaining, thread_id)
        )

    async def _finish_detached(self, task: asyncio.Task, remaining: float, thread_id: str) -> None:
        try:
            await asyncio.wait_for(asyncio.shield(task), remaining)
        except asyncio.TimeoutError:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await self._abandon(thread_id)
        except Exception:
            pass  # the run reported its own failure; nothing to close out
        finally:
            DETACHED_RUNS.pop(thread_id, None)

    async def _abandon(self, thread_id: str) -> None:
        if self._bridge.abandon_run is None:
            return
        try:
            await self._bridge.abandon_run({"configurable": {"thread_id": thread_id}})
        except Exception as exc:  # pragma: no cover - checkpointer dependent
            print(f"--- [Voice] Could not close out the cancelled run: {type(exc).__name__} ---", flush=True)

    # --- buffered input ----------------------------------------------------
    def buffer(self, text: str, trace: TurnTrace) -> None:
        self.buffered.append((text, trace))

    def take_buffered(self) -> tuple[str, TurnTrace, list[TurnTrace]] | None:
        """All buffered turns as one input: (text, last trace, earlier traces)."""
        if not self.buffered:
            return None
        texts = [text for text, _ in self.buffered]
        traces = [trace for _, trace in self.buffered]
        self.buffered = []
        return "，".join(texts), traces[-1], traces[:-1]

    # --- the run itself ----------------------------------------------------
    async def _emit(self, item: tuple) -> None:
        if not self._detached:
            await self._post(item)

    async def _drive(self, run: Run, text: str, thread_id: str, user_info: dict) -> None:
        config = {"configurable": {"thread_id": thread_id, "channel": "voice"}}
        state = self._bridge.build_state(text, user_info, "voice")
        try:
            graph_input: Any = await self._bridge.resolve_input(config, state, state, text)
            if graph_input is None:
                graph_input = state
            async for event in self._bridge.iter_events(
                graph_input, config, custom_types=VOICE_CUSTOM_TYPES
            ):
                await self._emit(("graph_event", run.token, event))
            await self._emit(("graph_done", run.token, None))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"--- [Voice] Graph run failed: {type(exc).__name__} ---", flush=True)
            await self._emit(("graph_done", run.token, "error"))
