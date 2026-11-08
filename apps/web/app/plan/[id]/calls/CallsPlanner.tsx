"use client";

import type { PgOut } from "@schemas";
import { useEffect, useState } from "react";

type Batch = { id: string; pgs: { pg_id: string; name: string }[] };
type Approved = { calls: { call_id: string; pg_name: string }[]; skipped: string[] };

const MAX_PGS = 5;

async function detail(res: Response): Promise<string> {
  const body = await res.json().catch(() => null);
  return typeof body?.detail === "string" ? body.detail : "Something went wrong. Please try again.";
}

export default function CallsPlanner({ planId }: { planId: string }) {
  const [pgs, setPgs] = useState<PgOut[] | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [batch, setBatch] = useState<Batch | null>(null);
  const [approved, setApproved] = useState<Approved | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    (async () => {
      const res = await fetch(`/api/proxy/v1/plans/${planId}/pgs`).catch(() => null);
      if (!res) return setError("Could not reach the service.");
      if (res.status === 401) {
        window.location.href = "/signin";
        return;
      }
      if (!res.ok) return setError(await detail(res));
      setPgs((await res.json()) as PgOut[]);
    })();
  }, [planId]);

  function toggle(id: string) {
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else if (next.size < MAX_PGS) next.add(id);
      return next;
    });
  }

  async function review() {
    setBusy(true);
    setError("");
    const res = await fetch(`/api/proxy/v1/plans/${planId}/call-batches`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ pg_ids: [...picked] }),
    }).catch(() => null);
    setBusy(false);
    if (!res) return setError("Could not reach the service.");
    if (!res.ok) return setError(await detail(res));
    setBatch((await res.json()) as Batch);
  }

  async function approve() {
    if (!batch) return;
    setBusy(true);
    setError("");
    const res = await fetch(`/api/proxy/v1/call-batches/${batch.id}/approve`, {
      method: "POST",
    }).catch(() => null);
    setBusy(false);
    if (!res) return setError("Could not reach the service.");
    if (!res.ok) return setError(await detail(res));
    setApproved((await res.json()) as Approved);
  }

  if (error && !pgs) return <p role="alert" style={{ color: "#b00020" }}>{error}</p>;
  if (!pgs) return <p role="status">Loading PGs...</p>;

  if (approved) {
    return (
      <>
        <p role="status">Approved. Start each call below.</p>
        <ul>
          {approved.calls.map((c) => (
            <li key={c.call_id}>
              {c.pg_name} · <a href={`/call/${c.call_id}`}>Start demo call</a>
            </li>
          ))}
        </ul>
        <p>
          <a href={`/plan/${planId}/comparison`}>See the PG comparison</a>
        </p>
        {approved.skipped.length > 0 && (
          <p>Not called, no longer available: {approved.skipped.join(", ")}.</p>
        )}
      </>
    );
  }

  if (batch) {
    return (
      <>
        <h2>Approve these calls</h2>
        <p>
          An AI assistant will call these PGs for you. It will say at the start that it is an AI,
          and it will only ask about rent, deposit, food, availability, rules and notice period. It
          will stop right away if the owner asks.
        </p>
        <ul>{batch.pgs.map((p) => <li key={p.pg_id}>{p.name}</li>)}</ul>
        {error && <p role="alert" style={{ color: "#b00020" }}>{error}</p>}
        <button onClick={approve} disabled={busy}>{busy ? "Approving..." : "Approve calls"}</button>
      </>
    );
  }

  if (pgs.length === 0) return <p>No PGs have agreed to AI calls in this area yet.</p>;

  return (
    <>
      <p>Pick up to {MAX_PGS} PGs. Only PGs that agreed to AI calls are shown.</p>
      <ul style={{ listStyle: "none", padding: 0 }}>
        {pgs.map((p) => (
          <li key={p.id} style={{ margin: "6px 0" }}>
            <label>
              <input
                type="checkbox"
                checked={picked.has(p.id)}
                onChange={() => toggle(p.id)}
                disabled={!picked.has(p.id) && picked.size >= MAX_PGS}
              />{" "}
              {p.name} <small>({p.area_name})</small>
            </label>
          </li>
        ))}
      </ul>
      {error && <p role="alert" style={{ color: "#b00020" }}>{error}</p>}
      <button onClick={review} disabled={busy || picked.size === 0}>
        {busy ? "Please wait..." : `Review ${picked.size} call${picked.size === 1 ? "" : "s"}`}
      </button>
    </>
  );
}
