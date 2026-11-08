"use client";

import type { AgreementCreated, ReportOut, RiskOut } from "@schemas";
import { ChangeEvent, useEffect, useRef, useState } from "react";

const ALLOWED = ["application/pdf", "image/jpeg", "image/png"];
const MAX_BYTES = 15 * 1024 * 1024;
const POLL_MS = 2000;
const POLL_LIMIT = 45; // about 90 seconds

type Phase = "choose" | "working" | "report";

// Shown on every screen of this feature, whatever the result.
const NOTICE =
  "This is not legal advice. It is an automated reading of your agreement to help you ask better questions. It can miss things or get things wrong. For a serious issue, or before you sign or pay, speak to a lawyer.";

const SEVERITY: Record<string, { label: string; color: string; bg: string }> = {
  high: { label: "High risk", color: "#8a1c1c", bg: "#fdecea" },
  medium: { label: "Medium risk", color: "#7a4b00", bg: "#fff4e0" },
  low: { label: "Low risk", color: "#1d4f7a", bg: "#e8f1fb" },
};

const TYPE_LABEL: Record<string, string> = {
  lock_in: "Lock-in period",
  deposit_deduction: "Deposit",
  notice_period: "Notice period",
  rent_increase: "Rent increase",
  early_exit_penalty: "Leaving early",
  owner_entry: "Owner entering your room",
  eviction_terms: "Being asked to leave",
  other: "Other",
};

async function detail(res: Response): Promise<string> {
  const body = await res.json().catch(() => null);
  return typeof body?.detail === "string" ? body.detail : "Something went wrong. Please try again.";
}

function Notice() {
  return (
    <p role="note" style={{ background: "#eef2f7", border: "1px solid #b7c3d4", padding: 12, borderRadius: 8 }}>
      <strong>Not legal advice.</strong> {NOTICE.replace("This is not legal advice. ", "")}
    </p>
  );
}

function RiskCard({ risk }: { risk: RiskOut }) {
  const sev = SEVERITY[risk.severity] ?? SEVERITY.medium;
  return (
    <li style={{ border: "1px solid #ddd", borderRadius: 8, padding: 16, marginBottom: 12, listStyle: "none" }}>
      <p style={{ margin: "0 0 8px" }}>
        <span style={{ background: sev.bg, color: sev.color, padding: "2px 8px", borderRadius: 4, fontWeight: 600 }}>
          {sev.label}
        </span>{" "}
        <strong>{TYPE_LABEL[risk.type] ?? "Other"}</strong>
        {risk.page != null && <span style={{ color: "#666" }}> · page {risk.page}</span>}
      </p>
      <blockquote style={{ margin: "8px 0", padding: "6px 12px", borderLeft: "3px solid #bbb", background: "#fafafa" }}>
        <small style={{ color: "#666" }}>The agreement says:</small>
        <div>{risk.quote}</div>
        {risk.quote_translation && (
          <div style={{ marginTop: 6, color: "#333" }}>
            <small style={{ color: "#666" }}>In English:</small> {risk.quote_translation}
          </div>
        )}
      </blockquote>
      <p style={{ margin: "8px 0" }}>{risk.explanation}</p>
      <p style={{ margin: "8px 0" }}>
        <strong>Ask the owner:</strong> {risk.question_to_ask}
      </p>
      {risk.source === "rules" && (
        <small style={{ color: "#666" }}>Found by a basic keyword check.</small>
      )}
    </li>
  );
}

export default function AgreementChecker({ planId }: { planId: string }) {
  const [phase, setPhase] = useState<Phase>("choose");
  const [error, setError] = useState("");
  const [report, setReport] = useState<ReportOut | null>(null);
  const [step, setStep] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  async function fetchReport(id: string): Promise<ReportOut | null> {
    const res = await fetch(`/api/proxy/v1/agreements/${id}/report`).catch(() => null);
    if (!res || !res.ok) return null;
    return (await res.json()) as ReportOut;
  }

  async function onPick(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setError("");
    if (!ALLOWED.includes(file.type)) return setError("Please choose a PDF, JPEG or PNG file.");
    if (file.size === 0) return setError("That file is empty.");
    if (file.size > MAX_BYTES) return setError("That file is too large. The limit is 15 MB.");

    setPhase("working");
    setStep("Preparing upload...");
    const created = await fetch("/api/proxy/v1/agreements", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        plan_id: planId, filename: file.name.slice(0, 120), content_type: file.type, size_bytes: file.size,
      }),
    }).catch(() => null);
    if (!created) return fail("Could not reach the service.");
    if (created.status === 401) {
      window.location.href = "/signin";
      return;
    }
    if (!created.ok) return fail(await detail(created));
    const link = (await created.json()) as AgreementCreated;

    setStep("Uploading your file...");
    const up = await fetch(`/api/proxy/${link.upload_url.replace(/^\//, "")}`, {
      method: "PUT",
      headers: { "content-type": file.type },
      body: file,
    }).catch(() => null);
    if (!up) return fail("The upload was interrupted. Please try again.");
    if (!up.ok) return fail(await detail(up));

    setStep("Reading and checking your agreement...");
    const start = await fetch(`/api/proxy/v1/agreements/${link.id}/analyze`, { method: "POST" }).catch(() => null);
    if (!start || !start.ok) return fail(start ? await detail(start) : "Could not reach the service.");

    for (let i = 0; i < POLL_LIMIT && alive.current; i++) {
      await new Promise((r) => setTimeout(r, POLL_MS));
      const r = await fetchReport(link.id);
      if (r && r.status !== "analyzing") {
        setReport(r);
        setPhase("report");
        return;
      }
    }
    if (alive.current) fail("This is taking longer than usual. Please try again in a minute.");
  }

  function fail(message: string) {
    if (!alive.current) return;
    setError(message);
    setPhase("choose");
  }

  function reset() {
    setReport(null);
    setError("");
    setPhase("choose");
  }

  return (
    <>
      <Notice />

      {phase === "choose" && (
        <section>
          <p>
            Upload your rental or PG agreement as a PDF (up to 20 pages) or a clear photo. We will
            point out clauses that could cost you money, and suggest questions to ask the owner.
          </p>
          <p style={{ color: "#555" }}>
            Your file is stored privately and deleted after 90 days. While testing, please use sample
            agreements only.
          </p>
          <input
            ref={input}
            type="file"
            accept="application/pdf,image/jpeg,image/png"
            onChange={onPick}
            aria-label="Choose your agreement file"
          />
          {error && <p role="alert" style={{ color: "#b00020" }}>{error}</p>}
        </section>
      )}

      {phase === "working" && <p role="status">{step} This can take up to a minute.</p>}

      {phase === "report" && report && (
        <section>
          {report.status === "done" && (
            <>
              <h2 style={{ marginBottom: 4 }}>
                {report.risks.length === 0
                  ? "No clear risks found"
                  : `${report.risks.length} thing${report.risks.length === 1 ? "" : "s"} to ask about`}
              </h2>
              {report.risks.length > 0 && (
                <p style={{ color: "#555", marginTop: 0 }}>
                  {report.risk_counts.high} high · {report.risk_counts.medium} medium · {report.risk_counts.low} low
                </p>
              )}
              {report.risks.length === 0 && (
                <p>
                  We did not find a clear problem, but that does not mean the agreement is safe. Read
                  it fully before you sign.
                </p>
              )}
              {report.warnings.map((w) => (
                <p key={w} role="note" style={{ background: "#fff4e0", padding: 10, borderRadius: 6 }}>{w}</p>
              ))}
              <ol style={{ padding: 0 }}>
                {report.risks.map((r, i) => <RiskCard key={i} risk={r} />)}
              </ol>
            </>
          )}
          {report.status === "unreadable" && (
            <>
              <h2>We could not read this file</h2>
              <p role="alert">{report.message}</p>
            </>
          )}
          {report.status === "failed" && (
            <>
              <h2>We could not check this file</h2>
              <p role="alert">{report.message}</p>
            </>
          )}
          <Notice />
          <button onClick={reset}>Check another agreement</button>
        </section>
      )}
    </>
  );
}
