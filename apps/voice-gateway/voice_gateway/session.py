"""One live call: browser audio in, model audio out, with the safety rules enforced in code.

What the code guarantees, whatever the model says:
- the call only runs while the approval, consent and opt-out checks still pass;
- a stop request in the owner's speech ends the call and revokes consent;
- the call is ended if the agent never discloses that it is an AI;
- facts are saved to the database the moment they are stated;
- a dropped model connection is resumed from a saved handle.
"""

import asyncio
import logging
import re
import time
from collections.abc import Callable
from typing import Protocol

from nguit_tools.call_gate import CALL_FIELDS, CallBlocked, CallContext

from voice_gateway.live import (
    AudioOut,
    BackendClosed,
    GoAway,
    Interrupted,
    InTranscript,
    LiveBackend,
    OutTranscript,
    Resumption,
    ToolCall,
    TurnComplete,
)
from voice_gateway.prompt import CONFIRM_STOP_KICK, DISCLOSURE_PHRASE, OPENING_KICK
from voice_gateway.stopwords import (
    answer_to_stop_question,
    is_end_request,
    is_stop_request,
    needs_stop_confirmation,
)
from voice_gateway.store import CallStore

log = logging.getLogger(__name__)

RESUME_NOTE = "The connection dropped and came back. Continue the call politely where you left off."
MAX_FACT_CHARS = 300
# How many times we ask "Would you like me to stop calling you?" before we stop asking and
# treat repeated signals as a stop. An owner who keeps sounding annoyed has told us enough.
MAX_STOP_QUESTIONS = 2


class StopClassifier(Protocol):
    """Optional second opinion on whether an owner utterance means "stop calling me".

    A model that understands meaning can catch phrasings no pattern list does. It can only
    make the agent ASK; it never opts a PG out by itself."""

    async def means_stop(self, text: str) -> bool: ...


def _variants(chunks: list[str]) -> list[str]:
    """Transcript chunks may split a word ("A" + "I") or not. Check both ways of joining."""
    return ["".join(chunks), " ".join(chunks)]


def _discloses(text: str) -> bool:
    said = text.lower()
    return bool(re.search(r"\b(ai|artificial)\b", said)) and DISCLOSURE_PHRASE in said


class Transport(Protocol):
    async def recv(self) -> bytes | dict | None: ...
    async def send_audio(self, data: bytes) -> None: ...
    async def send_json(self, data: dict) -> None: ...
    async def close(self) -> None: ...


class CallSession:
    def __init__(
        self,
        ctx: CallContext,
        store: CallStore,
        transport: Transport,
        backend_factory: Callable[[CallContext], LiveBackend],
        *,
        max_seconds: float = 300,
        max_reconnects: int = 5,
        opt_out_grace_seconds: float = 10,
        reconnect_delay: float = 0.5,
        stop_classifier: StopClassifier | None = None,
    ):
        self.ctx, self.store, self.transport, self.factory = ctx, store, transport, backend_factory
        self.stop_classifier = stop_classifier
        self.max_seconds = max_seconds
        self.max_reconnects = max_reconnects
        self.grace_seconds = opt_out_grace_seconds
        self.reconnect_delay = reconnect_delay

        self.result: tuple[str, str] | None = None
        self.opted_out = False
        self.handle: str | None = None
        self._ended = asyncio.Event()
        self._t0 = time.monotonic()
        self._kicked = False
        self._buf: dict[str, list[str]] = {"owner": [], "agent": []}
        self._start: dict[str, int] = {}
        self._agent_chunks: list[str] = []
        self._disclosed = False
        self._undisclosed_turns = 0
        self._grace_task: asyncio.Task | None = None
        self._awaiting_stop_answer = False
        self._stop_questions = 0

    # -- small helpers -------------------------------------------------------------------
    def _offset_ms(self) -> int:
        return int((time.monotonic() - self._t0) * 1000)

    def _end(self, status: str, reason: str) -> None:
        if self.result is None:
            self.result = (status, reason)
            self._ended.set()

    async def _flush(self, speaker: str) -> str:
        """Saves what one speaker said this turn and returns it ("" if nothing)."""
        text = " ".join(self._buf[speaker]).strip()
        self._buf[speaker] = []
        if text:
            await self.store.segment(speaker, self._start.pop(speaker, 0), text)
        return text

    async def _opt_out(self, source: str) -> None:
        if self.opted_out:
            return
        self.opted_out = True
        await self.store.opt_out(self.ctx.pg_id, source)
        # An alert watches for spikes of these. No phone number or name is logged.
        log.warning(
            "owner opted out",
            extra={"event": "owner_opt_out", "call_id": str(self.ctx.call_id), "source": source},
        )

    # -- main flow -----------------------------------------------------------------------
    async def run(self) -> None:
        self._t0 = time.monotonic()
        await self.store.mark_in_progress()
        await self.transport.send_json({"type": "state", "state": "connected"})
        try:
            async with asyncio.timeout(self.max_seconds):
                await self._backend_loop()
        except TimeoutError:
            self._end("completed", "max_duration")
        except Exception:
            log.exception("call %s crashed", self.ctx.call_id)
            self._end("failed", "internal_error")
        finally:
            await self._finish()

    async def _backend_loop(self) -> None:
        reconnects = 0
        self.handle = await self.store.handle()
        while self.result is None:
            backend = self.factory(self.ctx)
            try:
                await backend.connect(self.handle)
                if not self._kicked:
                    self._kicked = True
                    await backend.send_text(OPENING_KICK)
                elif self.handle is None:
                    await backend.send_text(RESUME_NOTE)  # no saved context to resume from
                await self._pump(backend)
            except BackendClosed:
                reconnects += 1
                if reconnects > self.max_reconnects:
                    self._end("failed", "reconnect_failed")
                    break
                try:
                    await self.store.gate()  # still approved, consented and not opted out?
                except CallBlocked as blocked:
                    if not self.opted_out:
                        self._end("failed", blocked.reason)
                    break
                await self.transport.send_json({"type": "reconnecting"})
                await asyncio.sleep(min(self.reconnect_delay * reconnects, 2))
            finally:
                try:
                    await backend.close()
                except Exception:
                    log.debug("backend close failed", exc_info=True)

    async def _pump(self, backend: LiveBackend) -> None:
        tasks = {
            asyncio.create_task(self._inbound(backend)),
            asyncio.create_task(self._outbound(backend)),
            asyncio.create_task(self._ended.wait()),
        }
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            task.result()  # re-raises BackendClosed so the loop can resume

    async def _inbound(self, backend: LiveBackend) -> None:
        while True:
            msg = await self.transport.recv()
            if msg is None:
                self._end("ended_by_owner", "browser_closed")
                return
            if isinstance(msg, dict):
                if msg.get("type") == "end":
                    self._end("ended_by_owner", "owner_hung_up")
                    return
                continue
            if self.result is not None:
                return
            try:
                await backend.send_audio(msg)
            except Exception as exc:
                raise BackendClosed(type(exc).__name__) from exc

    async def _outbound(self, backend: LiveBackend) -> None:
        async for event in backend.events():
            await self._on_event(event, backend)
            if self.result is not None:
                return

    # -- model events --------------------------------------------------------------------
    async def _on_event(self, ev, backend: LiveBackend) -> None:
        if isinstance(ev, AudioOut):
            await self.transport.send_audio(ev.data)
        elif isinstance(ev, InTranscript):
            await self._on_owner_speech(ev.text)
        elif isinstance(ev, OutTranscript):
            self._start.setdefault("agent", self._offset_ms())
            self._buf["agent"].append(ev.text)
            self._agent_chunks.append(ev.text)
            await self.transport.send_json(
                {"type": "transcript", "speaker": "agent", "text": ev.text}
            )
        elif isinstance(ev, Interrupted):
            await self.transport.send_json({"type": "interrupted"})  # browser stops playback
            await self._end_of_agent_turn()
        elif isinstance(ev, TurnComplete):
            owner_said = await self._flush("owner")
            await self._after_owner_turn(owner_said, backend)
            await self._end_of_agent_turn()
        elif isinstance(ev, ToolCall):
            await self._on_tool(ev, backend)
        elif isinstance(ev, Resumption):
            self.handle = ev.handle
            await self.store.set_handle(ev.handle)
        elif isinstance(ev, GoAway):
            raise BackendClosed("go_away")  # reconnect now, using the saved handle

    async def _on_owner_speech(self, text: str) -> None:
        self._start.setdefault("owner", self._offset_ms())
        self._buf["owner"].append(text)
        await self.transport.send_json({"type": "transcript", "speaker": "owner", "text": text})
        # Deterministic stop check on what the owner said so far in this turn.
        variants = _variants(self._buf["owner"])
        if any(is_stop_request(v) for v in variants):
            await self._flush("owner")
            await self._opt_out("stop_phrase")
            self._end("opted_out", "stop_phrase")
        elif any(is_end_request(v) for v in variants):
            # "End this call", "I have to go", "bye": this call ends, and nothing else changes.
            await self._flush("owner")
            self._end("ended_by_owner", "owner_asked_to_end")

    async def _after_owner_turn(self, said: str, backend: LiveBackend) -> None:
        """Runs when the owner has finished a turn. Handles "Would you like me to stop?"."""
        if not said or self.result is not None or self.opted_out:
            return  # nothing from the owner (the agent's own turn ended), or already ending

        if self._awaiting_stop_answer:
            self._awaiting_stop_answer = False
            answer = answer_to_stop_question(said)
            if answer == "yes":
                await self._opt_out("confirmed_stop")
                self._end("opted_out", "confirmed_stop")
                return
            if answer == "no":
                return
            # unclear: carry on, but the owner's words are still checked below

        signal = needs_stop_confirmation(said)
        if not signal and self.stop_classifier is not None:
            try:
                signal = await self.stop_classifier.means_stop(said)
            except Exception:  # a classifier outage must never break a call
                log.warning("stop classifier failed", exc_info=True)
        if not signal:
            return

        self._stop_questions += 1
        if self._stop_questions > MAX_STOP_QUESTIONS:
            await self._opt_out("repeated_signals")
            self._end("opted_out", "repeated_signals")
            return
        log.info(
            "asking whether to stop",
            extra={"event": "stop_confirmation_asked", "call_id": str(self.ctx.call_id)},
        )
        self._awaiting_stop_answer = True
        try:
            await backend.send_text(CONFIRM_STOP_KICK)
        except Exception as exc:
            raise BackendClosed(type(exc).__name__) from exc

    async def _end_of_agent_turn(self) -> None:
        had_speech = bool(self._buf["agent"])
        await self._flush("agent")
        if self._disclosed or not had_speech:
            return
        if any(_discloses(v) for v in _variants(self._agent_chunks)):
            self._disclosed = True
            return
        self._undisclosed_turns += 1
        if self._undisclosed_turns >= 2:  # the opening must say who is calling and that it is AI
            await self.store.audit("disclosure_missing", {})
            self._end("failed", "disclosure_missing")

    # -- tools ---------------------------------------------------------------------------
    async def _on_tool(self, ev: ToolCall, backend: LiveBackend) -> None:
        if not self.opted_out:
            try:
                await self.store.gate()
            except CallBlocked as blocked:
                self._end("failed", blocked.reason)
                return
        result = await self._run_tool(ev)
        try:
            await backend.send_tool_result(ev.id, ev.name, result)
        except Exception:
            log.debug("could not send tool result", exc_info=True)  # call may be ending

    async def _run_tool(self, ev: ToolCall) -> dict:
        if ev.name == "record_fact":
            field = str(ev.args.get("field", ""))
            if self.opted_out:
                return {"ignored": "the owner opted out"}
            if field not in CALL_FIELDS:
                return {"error": f"field must be one of {', '.join(CALL_FIELDS)}"}
            value = str(ev.args.get("value", "")).strip()[:MAX_FACT_CHARS]
            if not value:
                return {"error": "value is empty"}
            confirmed = ev.args.get("confirmed") is True
            await self.store.fact(field, value, confirmed, self._offset_ms())
            return {"saved": True}
        if ev.name == "mark_opt_out":
            await self._opt_out("model_tool")
            self._grace_task = asyncio.create_task(self._end_after_grace())
            return {"ok": True, "next": "Apologize briefly in one sentence, then call end_call."}
        if ev.name == "end_call":
            self._end("opted_out" if self.opted_out else "completed", "agent_ended")
            return {"ok": True}
        return {"error": "unknown tool"}

    async def _end_after_grace(self) -> None:
        await asyncio.sleep(self.grace_seconds)
        self._end("opted_out", "grace_timeout")

    # -- wrap-up -------------------------------------------------------------------------
    async def _finish(self) -> None:
        if self._grace_task:
            self._grace_task.cancel()
        status, reason = self.result or ("failed", "unknown")
        try:
            await self._flush("owner")
            await self._flush("agent")
            await self.store.finish(status, reason)
            # One line per call, read by the call-outcome dashboard and the failure alert.
            log.info(
                "call ended",
                extra={
                    "event": "call_ended",
                    "call_id": str(self.ctx.call_id),
                    "status": status,
                    "reason": reason,
                    "duration_s": round(time.monotonic() - self._t0, 1),
                    "disclosed": self._disclosed,
                },
            )
            await self.transport.send_json({"type": "ended", "status": status, "reason": reason})
        except Exception:
            log.exception("could not finish call %s", self.ctx.call_id)
        finally:
            await self.transport.close()
