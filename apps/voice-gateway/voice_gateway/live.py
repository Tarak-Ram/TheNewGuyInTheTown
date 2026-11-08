"""The model side of a call, behind a small interface so tests can use a fake.

GeminiLiveBackend follows the google-genai Live API (client.aio.live.connect, with
send_realtime_input, send_tool_response, go_away and session_resumption_update).
Model IDs always come from the environment.
"""

import os
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Protocol

from voice_gateway.prompt import INSTRUCTION, TOOLS

LANGUAGE_CODES = {"en": "en-IN", "hi": "hi-IN", "te": "te-IN"}
INPUT_MIME = "audio/pcm;rate=16000"


class BackendClosed(Exception):
    """The model connection ended without us asking. The session may resume."""


@dataclass
class AudioOut:
    data: bytes  # 16-bit PCM, 24 kHz


@dataclass
class InTranscript:
    text: str  # what the owner said


@dataclass
class OutTranscript:
    text: str  # what the agent said


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class GoAway:
    seconds_left: float | None = None


@dataclass
class Resumption:
    handle: str


class TurnComplete: ...


class Interrupted: ...


Event = AudioOut | InTranscript | OutTranscript | ToolCall | GoAway | Resumption
Event = Event | TurnComplete | Interrupted


class LiveBackend(Protocol):
    async def connect(self, handle: str | None) -> None: ...
    async def send_audio(self, pcm: bytes) -> None: ...
    async def send_text(self, text: str) -> None: ...
    async def send_tool_result(self, call_id: str, name: str, result: dict) -> None: ...
    def events(self) -> AsyncIterator[Event]: ...
    async def close(self) -> None: ...


class GeminiLiveBackend:
    def __init__(self, language: str = "en"):
        self.language_code = LANGUAGE_CODES.get(language, "en-IN")
        self.models = [
            m
            for m in (
                os.environ.get("GEMINI_LIVE_MODEL"),
                os.environ.get("GEMINI_LIVE_FALLBACK_MODEL"),
            )
            if m
        ]
        self._stack = AsyncExitStack()
        self._session = None

    async def connect(self, handle: str | None) -> None:
        from google import genai
        from google.genai import types

        if not self.models:
            raise BackendClosed("GEMINI_LIVE_MODEL is not set")
        client = genai.Client()  # GOOGLE_API_KEY / GEMINI_API_KEY, or Vertex env settings
        config = types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            system_instruction=INSTRUCTION,
            tools=TOOLS,
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            session_resumption=types.SessionResumptionConfig(handle=handle),
            speech_config=types.SpeechConfig(language_code=self.language_code),
        )
        last_error: Exception | None = None
        for model in self.models:  # primary first, then the fallback model
            try:
                cm = client.aio.live.connect(model=model, config=config)
                self._session = await self._stack.enter_async_context(cm)
                return
            except Exception as exc:
                last_error = exc
        raise BackendClosed(f"could not open a Live session: {type(last_error).__name__}")

    async def send_audio(self, pcm: bytes) -> None:
        from google.genai import types

        await self._session.send_realtime_input(audio=types.Blob(data=pcm, mime_type=INPUT_MIME))

    async def send_text(self, text: str) -> None:
        await self._session.send_realtime_input(text=text)

    async def send_tool_result(self, call_id: str, name: str, result: dict) -> None:
        from google.genai import types

        await self._session.send_tool_response(
            function_responses=types.FunctionResponse(id=call_id, name=name, response=result)
        )

    async def events(self) -> AsyncIterator[Event]:
        try:
            while True:  # receive() ends after each model turn, so loop for the whole call
                async for msg in self._session.receive():
                    sc = msg.server_content
                    if sc:
                        if sc.interrupted:
                            yield Interrupted()
                        if sc.input_transcription and sc.input_transcription.text:
                            yield InTranscript(sc.input_transcription.text)
                        if sc.output_transcription and sc.output_transcription.text:
                            yield OutTranscript(sc.output_transcription.text)
                        if sc.model_turn and sc.model_turn.parts:
                            for part in sc.model_turn.parts:
                                if part.inline_data and part.inline_data.data:
                                    yield AudioOut(part.inline_data.data)
                        if sc.turn_complete:
                            yield TurnComplete()
                    if msg.tool_call and msg.tool_call.function_calls:
                        for fc in msg.tool_call.function_calls:
                            yield ToolCall(fc.id or "", fc.name or "", dict(fc.args or {}))
                    if msg.go_away:
                        yield GoAway()
                    upd = msg.session_resumption_update
                    if upd and upd.resumable and upd.new_handle:
                        yield Resumption(upd.new_handle)
        except Exception as exc:
            raise BackendClosed(type(exc).__name__) from exc

    async def close(self) -> None:
        await self._stack.aclose()
