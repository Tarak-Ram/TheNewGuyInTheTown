"use client";

import { useState } from "react";

export default function SignOutButton() {
  const [busy, setBusy] = useState(false);
  async function signOut() {
    setBusy(true);
    await fetch("/api/auth/logout", { method: "POST" }).catch(() => null);
    window.location.href = "/";
  }
  return (
    <button className="secondary" onClick={signOut} disabled={busy}>
      {busy ? "Signing out..." : "Sign out"}
    </button>
  );
}
