"use client";

import { useEffect, useRef, useState } from "react";

type Line = { speaker: "agent" | "owner"; text: string };
type Phase = "idle" | "connecting" | "live" | "ended" | "error";

const REASONS: Record<string, string> = {
  stop_phrase: "The owner asked to stop. The PG will not be called again.",
  agent_ended: "The call finished.",
  owner_hung_up: "You ended the call.",
  browser_closed: "The call was closed.",
  max_duration: "The call reached its time limit.",
  disclosure_missing: "The call was stopped because the assistant did not say it is an AI.",
  reconnect_failed: "The connection was lost and could not be restored.",
  call_finished: "This call has already finished.",
  not_approved: "This call has not been approved.",
  no_consent: "This PG can no longer be called.",
  token_already_used: "This call link was already used.",
  invalid_token: "This call link is not valid. Please start again.",
};

export default function DemoCall({ callId, gatewayUrl }: { callId: string; gatewayUrl: string }) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [lines, setLines] = useState<Line[]>([]);
  const [note, setNote] = useState("");
  const ws = useRef<WebSocket | null>(null);
  const mic = useRef<MediaStream | null>(null);
  const capture = useRef<AudioContext | null>(null);
  const playback = useRef<AudioContext | null>(null);
  const playing = useRef<Set<AudioBufferSourceNode>>(new Set());
  const nextTime = useRef(0);

  function stopPlayback() {
    for (const src of playing.current) {
      try {
        src.stop();
      } catch {
        /* already stopped */
      }
    }
    playing.current.clear();
    nextTime.current = 0;
  }

  function cleanup() {
    stopPlayback();
    mic.current?.getTracks().forEach((t) => t.stop());
    void capture.current?.close();
    void playback.current?.close();
    mic.current = capture.current = playback.current = null;
  }

  useEffect(() => () => { ws.current?.close(); cleanup(); }, []);

  function playChunk(data: ArrayBuffer) {
    const ctx = playback.current;
    if (!ctx) return;
    const pcm = new Int16Array(data);
    const buf = ctx.createBuffer(1, pcm.length, 24000); // the model speaks at 24 kHz
    const ch = buf.getChannelData(0);
    for (let i = 0; i < pcm.length; i++) ch[i] = pcm[i] / 0x8000;
    const src = ctx.createBufferSource();
    src.buffer = buf;
    src.connect(ctx.destination);
    nextTime.current = Math.max(nextTime.current, ctx.currentTime);
    src.start(nextTime.current);
    nextTime.current += buf.duration;
    playing.current.add(src);
    src.onended = () => playing.current.delete(src);
  }

  async function start() {
    setPhase("connecting");
    setNote("");
    setLines([]);
    try {
      const res = await fetch(`/api/proxy/v1/calls/${callId}/web-session`, { method: "POST" });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(typeof body?.detail === "string" ? body.detail : "Could not start the call.");
      }
      const { token } = (await res.json()) as { token: string };

      mic.current = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
      capture.current = new AudioContext({ sampleRate: 16000 });
      playback.current = new AudioContext({ sampleRate: 24000 });
      await capture.current.audioWorklet.addModule("/pcm-capture.js");

      const socket = new WebSocket(`${gatewayUrl}/v1/calls/${callId}/web?token=${encodeURIComponent(token)}`);
      socket.binaryType = "arraybuffer";
      ws.current = socket;

      socket.onopen = () => {
        const source = capture.current!.createMediaStreamSource(mic.current!);
        const node = new AudioWorkletNode(capture.current!, "pcm-capture");
        node.port.onmessage = (e) => {
          if (socket.readyState === WebSocket.OPEN) socket.send(e.data as ArrayBuffer);
        };
        source.connect(node);
      };
      socket.onmessage = (e) => {
        if (e.data instanceof ArrayBuffer) return playChunk(e.data);
        const msg = JSON.parse(e.data as string);
        if (msg.type === "state") setPhase("live");
        else if (msg.type === "reconnecting") setNote("Reconnecting...");
        else if (msg.type === "interrupted") stopPlayback(); // agent stops the moment you speak
        else if (msg.type === "transcript") {
          setNote("");
          setLines((prev) => {
            const last = prev[prev.length - 1];
            if (last && last.speaker === msg.speaker) {
              return [...prev.slice(0, -1), { ...last, text: last.text + msg.text }];
            }
            return [...prev, { speaker: msg.speaker, text: msg.text }];
          });
        } else if (msg.type === "ended") {
          setNote(REASONS[msg.reason] ?? "The call ended.");
          setPhase("ended");
          cleanup();
        }
      };
      socket.onerror = () => {
        setNote("Could not connect to the voice service.");
        setPhase("error");
        cleanup();
      };
      socket.onclose = () => {
        setPhase((p) => (p === "live" || p === "connecting" ? "ended" : p));
        cleanup();
      };
    } catch (err) {
      cleanup();
      setNote(err instanceof Error ? err.message : "Could not start the call.");
      setPhase("error");
    }
  }

  function hangUp() {
    ws.current?.send(JSON.stringify({ type: "end" }));
  }

  return (
    <section>
      {(phase === "idle" || phase === "error" || phase === "ended") && (
        <button onClick={start}>{phase === "idle" ? "Start demo call" : "Try again"}</button>
      )}
      {phase === "connecting" && <p role="status">Connecting...</p>}
      {phase === "live" && (
        <>
          <p role="status">Call in progress. Speak as the PG owner. Use a headset to avoid echo.</p>
          <button onClick={hangUp}>End call</button>
        </>
      )}
      {note && <p role={phase === "error" ? "alert" : "status"}>{note}</p>}
      <ul style={{ listStyle: "none", padding: 0 }}>
        {lines.map((l, i) => (
          <li key={i} style={{ margin: "8px 0", textAlign: l.speaker === "agent" ? "left" : "right" }}>
            <small>{l.speaker === "agent" ? "AI assistant" : "You (demo owner)"}</small>
            <div>{l.text}</div>
          </li>
        ))}
      </ul>
    </section>
  );
}
