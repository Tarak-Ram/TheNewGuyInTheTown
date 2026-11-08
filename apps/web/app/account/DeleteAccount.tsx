"use client";

import { useState } from "react";

export default function DeleteAccount() {
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function remove() {
    setBusy(true);
    setError("");
    const res = await fetch("/api/proxy/v1/me?confirm=DELETE", { method: "DELETE" }).catch(() => null);
    if (!res || !res.ok) {
      setBusy(false);
      setError(
        res?.status === 401
          ? "You are already signed out."
          : "We could not delete your account. Please try again.",
      );
      return;
    }
    await fetch("/api/auth/logout", { method: "POST" }).catch(() => null);
    window.location.href = "/";
  }

  return (
    <section className="card">
      <h2 style={{ marginTop: 0 }}>Delete my account and data</h2>
      <p>
        This removes your move plans, area results, calls, transcripts, comparison tables and any
        agreements you uploaded, including the files. It happens straight away and cannot be undone.
      </p>
      <p>
        We keep a short record that an account was deleted, with no name, email or phone number.
      </p>
      <label htmlFor="confirm">Type DELETE to confirm</label>
      <input
        id="confirm"
        value={typed}
        onChange={(e) => setTyped(e.target.value)}
        autoComplete="off"
        style={{ display: "block", marginBottom: 12 }}
      />
      {error && <p role="alert" className="error">{error}</p>}
      <button
        onClick={remove}
        disabled={busy || typed !== "DELETE"}
        style={{ background: "#b00020", borderColor: "#b00020" }}
      >
        {busy ? "Deleting..." : "Delete everything"}
      </button>
    </section>
  );
}
