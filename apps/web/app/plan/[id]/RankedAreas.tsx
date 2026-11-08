"use client";

import type { RankResponse } from "@schemas";
import { useCallback, useEffect, useState } from "react";

type State =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "done"; data: RankResponse };

const rupees = (n: number) => `Rs ${n.toLocaleString("en-IN")}`;

export default function RankedAreas({ planId }: { planId: string }) {
  const [state, setState] = useState<State>({ kind: "loading" });

  const load = useCallback(async () => {
    setState({ kind: "loading" });
    const res = await fetch(`/api/proxy/v1/plans/${planId}/rank-areas`, { method: "POST" }).catch(
      () => null,
    );
    if (!res) return setState({ kind: "error", message: "Could not reach the service." });
    if (res.status === 401) {
      window.location.href = "/signin";
      return;
    }
    if (!res.ok) {
      const body = await res.json().catch(() => null);
      const message = typeof body?.detail === "string" ? body.detail : "Something went wrong.";
      return setState({ kind: "error", message });
    }
    setState({ kind: "done", data: (await res.json()) as RankResponse });
  }, [planId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (state.kind === "loading") return <p role="status">Checking commute times. This can take a few seconds...</p>;

  if (state.kind === "error") {
    return (
      <>
        <p role="alert" style={{ color: "#b00020" }}>{state.message}</p>
        <button onClick={load}>Try again</button>
        <p><a href={`/plan/${planId}/edit`}>Edit my details</a></p>
      </>
    );
  }

  const { data } = state;
  if (data.areas.length === 0) {
    return (
      <>
        <p>We could not find any areas to show.</p>
        <p><a href={`/plan/${planId}/edit`}>Change my details</a></p>
      </>
    );
  }

  return (
    <>
      {data.over_budget_all && (
        <p role="note" style={{ background: "#fff4e5", padding: 12 }}>
          No area has rents inside your budget. These are the closest options. The note on each
          area shows how much more per month you would need.
        </p>
      )}
      <p style={{ color: "#555" }}>Commute times: {data.commute_basis}.</p>
      <ol style={{ padding: 0, listStyle: "none" }}>
        {data.areas.map((a, i) => (
          <li key={a.area_id} style={{ border: "1px solid #ddd", borderRadius: 8, padding: 16, marginBottom: 12 }}>
            <h2 style={{ margin: "0 0 4px" }}>{i + 1}. {a.name}</h2>
            <p style={{ margin: "4px 0" }}><strong>{a.commute_minutes} min</strong> to your office</p>
            <p style={{ margin: "4px 0" }}>
              Rent: {rupees(a.rent_min)} to {rupees(a.rent_max)} a month
              {a.budget_gap > 0 && <> ({rupees(a.budget_gap)} over your budget)</>}
            </p>
            <p style={{ margin: "4px 0" }}>{a.reason}</p>
            <p style={{ margin: "4px 0", fontSize: 13, color: "#666" }}>
              Rent source: {a.rent_source}. Updated {a.rent_updated_at}.
            </p>
          </li>
        ))}
      </ol>
      {data.skipped_areas.length > 0 && (
        <p style={{ fontSize: 13, color: "#666" }}>
          Not shown, no commute data: {data.skipped_areas.join(", ")}.
        </p>
      )}
      <p>
        <a href={`/plan/${planId}/calls`}>Next: compare PGs by voice</a> |{" "}
        <a href={`/plan/${planId}/comparison`}>PG comparison</a> |{" "}
        <a href={`/plan/${planId}/agreement`}>Check an agreement</a> |{" "}
        <a href={`/plan/${planId}/edit`}>Edit my details</a>
      </p>
    </>
  );
}
