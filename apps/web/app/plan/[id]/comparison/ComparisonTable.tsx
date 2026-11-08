"use client";

import type { ComparisonOut } from "@schemas";
import { useCallback, useEffect, useRef, useState } from "react";

const LABELS: Record<string, string> = {
  rent: "Rent",
  deposit: "Deposit",
  food: "Food",
  availability: "Available",
  sharing_type: "Sharing",
  rules: "Rules",
  notice_period: "Notice",
};

const STATUS: Record<string, string> = {
  approved: "Call not started",
  connecting: "Connecting",
  in_progress: "On a call",
  completed: "Call finished",
  opted_out: "Owner asked not to be called",
  ended_by_owner: "Call ended early",
  failed: "Call failed",
  unreachable: "Not reached",
};

const FINISHED = new Set(["completed", "opted_out", "ended_by_owner", "failed", "unreachable"]);
const POLL_MS = 3000;
const POLL_LIMIT = 20; // stop after about a minute

function atTime(ms: number | null | undefined): string {
  if (ms == null) return "";
  const s = Math.round(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export default function ComparisonTable({ planId }: { planId: string }) {
  const [data, setData] = useState<ComparisonOut | null>(null);
  const [error, setError] = useState("");
  const polls = useRef(0);

  const load = useCallback(async () => {
    const res = await fetch(`/api/proxy/v1/plans/${planId}/comparison`).catch(() => null);
    if (!res) return setError("Could not reach the service.");
    if (res.status === 401) {
      window.location.href = "/signin";
      return;
    }
    if (!res.ok) {
      const body = await res.json().catch(() => null);
      return setError(typeof body?.detail === "string" ? body.detail : "Something went wrong.");
    }
    setError("");
    setData((await res.json()) as ComparisonOut);
  }, [planId]);

  useEffect(() => {
    void load();
  }, [load]);

  // While a finished call is still being checked, look again every few seconds.
  const waiting = data?.rows.some((r) => FINISHED.has(r.call_status) && !r.facts_checked) ?? false;
  useEffect(() => {
    if (!waiting || polls.current >= POLL_LIMIT) return;
    const t = setTimeout(() => {
      polls.current += 1;
      void load();
    }, POLL_MS);
    return () => clearTimeout(t);
  }, [waiting, data, load]);

  async function recheck(callId: string) {
    await fetch(`/api/proxy/v1/calls/${callId}/extract`, { method: "POST" }).catch(() => null);
    polls.current = 0;
    await load();
  }

  if (error && !data) {
    return (
      <>
        <p role="alert" style={{ color: "#b00020" }}>{error}</p>
        <button onClick={load}>Try again</button>
      </>
    );
  }
  if (!data) return <p role="status">Loading...</p>;
  if (data.rows.length === 0) {
    return (
      <>
        <p>No PG has been called yet.</p>
        <p><a href={`/plan/${planId}/calls`}>Choose PGs to call</a></p>
      </>
    );
  }

  const stuck = waiting && polls.current >= POLL_LIMIT;
  return (
    <>
      <p style={{ color: "#555" }}>
        Only what the owner clearly said is shown. Anything unclear, or not asked, says &quot;Not
        confirmed&quot;. Hover or tap a value to see the owner&apos;s words.
      </p>
      <p className="only-narrow" style={{ color: "#555" }}>
        Swipe the table sideways to see every column.
      </p>
      {waiting && !stuck && <p role="status">Checking what the owners said...</p>}
      <div style={{ overflowX: "auto" }}>
        <table style={{ borderCollapse: "collapse", minWidth: 640, width: "100%" }}>
          <thead>
            <tr>
              <th style={th}>PG</th>
              {data.field_order.map((f) => <th key={f} style={th}>{LABELS[f] ?? f}</th>)}
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row) => (
              <tr key={row.call_id}>
                <th scope="row" style={{ ...td, textAlign: "left", background: "#fafafa" }}>
                  {row.pg_name}
                  <div style={{ fontWeight: 400, fontSize: 12, color: "#666" }}>
                    {row.area_name} · {STATUS[row.call_status] ?? row.call_status}
                    {row.provider === "sample" && " · Pre-recorded sample"}
                  </div>
                  {FINISHED.has(row.call_status) && (!row.facts_checked || stuck) && (
                    <button onClick={() => recheck(row.call_id)} style={{ fontSize: 12 }}>
                      Check this call again
                    </button>
                  )}
                </th>
                {data.field_order.map((f) => {
                  const cell = row.fields[f];
                  const tip = cell.confirmed
                    ? `"${cell.quote ?? ""}" at ${atTime(cell.transcript_offset)}`
                    : undefined;
                  return (
                    <td key={f} style={td} title={tip}>
                      {cell.confirmed ? cell.display : (
                        <span style={{ color: "#777", fontStyle: "italic" }}>{cell.display}</span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {error && <p role="alert" style={{ color: "#b00020" }}>{error}</p>}
    </>
  );
}

const th = { textAlign: "left", padding: 8, borderBottom: "2px solid #ccc", fontSize: 13 } as const;
const td = { padding: 8, borderBottom: "1px solid #eee", verticalAlign: "top", fontSize: 14 } as const;
