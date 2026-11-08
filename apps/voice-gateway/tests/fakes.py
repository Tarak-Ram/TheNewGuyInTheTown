"""Test doubles for the model connection and the browser connection."""

import asyncio

from voice_gateway.live import BackendClosed

END = object()


class FakeBackend:
    """Scripted stand-in for the Gemini Live session. Feed it events before or during a run."""

    def __init__(self, *events, fail_connect: bool = False):
        self.queue: asyncio.Queue = asyncio.Queue()
        for e in events:
            self.queue.put_nowait(e)
        self.fail_connect = fail_connect
        self.connected_with = "never connected"
        self.audio: list[bytes] = []
        self.texts: list[str] = []
        self.tool_results: list[tuple[str, str, dict]] = []
        self.closed = False

    def feed(self, *events):
        for e in events:
            self.queue.put_nowait(e)

    async def connect(self, handle):
        if self.fail_connect:
            raise BackendClosed("cannot connect")
        self.connected_with = handle

    async def send_audio(self, pcm):
        self.audio.append(pcm)

    async def send_text(self, text):
        self.texts.append(text)

    async def send_tool_result(self, call_id, name, result):
        self.tool_results.append((call_id, name, result))

    async def events(self):
        while True:
            item = await self.queue.get()
            if isinstance(item, Exception):
                raise item
            if item is END:
                return
            yield item

    async def close(self):
        self.closed = True


class Factory:
    """Hands out the prepared backends in order, one per connection attempt."""

    def __init__(self, *backends):
        self.backends = list(backends)
        self.made = 0

    def __call__(self, ctx):
        backend = self.backends[min(self.made, len(self.backends) - 1)]
        self.made += 1
        return backend


class FakeTransport:
    def __init__(self):
        self.incoming: asyncio.Queue = asyncio.Queue()
        self.audio: list[bytes] = []
        self.json: list[dict] = []
        self.closed = False

    async def recv(self):
        return await self.incoming.get()

    async def send_audio(self, data):
        self.audio.append(data)

    async def send_json(self, data):
        self.json.append(data)

    async def close(self):
        self.closed = True

    def types(self):
        return [m.get("type") for m in self.json]
