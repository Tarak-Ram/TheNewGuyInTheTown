import type { Metadata, Viewport } from "next";
import { cookies } from "next/headers";
import type { ReactNode } from "react";
import SignOutButton from "../components/SignOutButton";
import "./globals.css";

export const metadata: Metadata = {
  title: "The New Guy in Town",
  description: "An AI helper for people moving to a new city.",
};

// Make the page fit the phone screen instead of a zoomed-out desktop layout.
export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export default async function RootLayout({ children }: { children: ReactNode }) {
  const signedIn = Boolean((await cookies()).get("session"));
  const demo = process.env.DEMO_MODE === "true";
  return (
    <html lang="en">
      <body>
        {demo && (
          <div className="demo-banner" role="note">
            <strong>Demo mode.</strong> Sample data only. Commute times are estimates, and no real
            PG owner is contacted.
          </div>
        )}
        <header className="site-header">
          <a className="brand" href="/">The New Guy in Town</a>
          {signedIn && (
            <span style={{ display: "flex", gap: 12, alignItems: "center" }}>
              <a href="/account">Account</a>
              <SignOutButton />
            </span>
          )}
        </header>
        <main className="page">{children}</main>
      </body>
    </html>
  );
}
