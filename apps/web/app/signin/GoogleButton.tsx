"use client";

import { useEffect, useRef, useState } from "react";

type GoogleId = {
  initialize: (cfg: { client_id: string; callback: (r: { credential: string }) => void }) => void;
  renderButton: (el: HTMLElement, opts: Record<string, string>) => void;
};

export default function GoogleButton({ clientId }: { clientId: string }) {
  const holder = useRef<HTMLDivElement>(null);
  const [message, setMessage] = useState("");

  useEffect(() => {
    const script = document.createElement("script");
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.onload = () => {
      const google = (window as unknown as { google: { accounts: { id: GoogleId } } }).google;
      google.accounts.id.initialize({
        client_id: clientId,
        callback: async ({ credential }) => {
          const res = await fetch("/api/auth/google", {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: JSON.stringify({ id_token: credential }),
          });
          setMessage(res.ok ? "Signed in." : "Sign-in failed. Please try again.");
          if (res.ok) window.location.href = "/";
        },
      });
      if (holder.current) google.accounts.id.renderButton(holder.current, { theme: "outline" });
    };
    document.body.appendChild(script);
    return () => script.remove();
  }, [clientId]);

  return (
    <>
      <div ref={holder} />
      <p role="status">{message}</p>
    </>
  );
}
