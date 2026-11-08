"use client";

import { useState } from "react";

export default function DemoSignIn() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function go() {
    setBusy(true);
    setError("");
    const res = await fetch("/api/auth/demo", { method: "POST" }).catch(() => null);
    if (!res || !res.ok) {
      setBusy(false);
      setError("Could not start the demo. Please try again.");
      return;
    }
    window.location.href = "/";
  }

  return (
    <>
      <button className="secondary" onClick={go} disabled={busy}>
        {busy ? "Starting..." : "Use the demo account"}
      </button>
      {error && <p role="alert" className="error">{error}</p>}
    </>
  );
}
