"use client";

import { usePathname } from "next/navigation";
import { useEffect, useRef } from "react";

const STEPS = ["Sign in", "Your move", "Areas", "Call PGs", "Compare", "Agreement"] as const;

function hrefFor(step: number, planId?: string): string | null {
  switch (step) {
    case 1:
      return "/";
    case 2:
      return planId ? `/plan/${planId}/edit` : "/plan/new";
    case 3:
      return planId ? `/plan/${planId}` : null;
    case 4:
      return planId ? `/plan/${planId}/calls` : null;
    case 5:
      return planId ? `/plan/${planId}/comparison` : null;
    case 6:
      return planId ? `/plan/${planId}/agreement` : null;
    default:
      return null;
  }
}

// Which stage the current page belongs to.
export function stepForPath(path: string): number {
  if (path.endsWith("/edit") || path === "/plan/new") return 2;
  if (path.endsWith("/calls") || path.startsWith("/call/")) return 4;
  if (path.endsWith("/comparison")) return 5;
  if (path.endsWith("/agreement")) return 6;
  if (path.startsWith("/plan/")) return 3;
  return 1;
}

export default function Stepper({ planId, current }: { planId?: string; current?: number }) {
  const path = usePathname() ?? "";
  const now = current ?? stepForPath(path);
  const list = useRef<HTMLOListElement>(null);

  // On a phone the row of steps scrolls sideways. Keep the current step in view.
  useEffect(() => {
    const row = list.current;
    const active = row?.querySelector<HTMLElement>('[aria-current="step"]');
    if (row && active) {
      row.scrollLeft = active.offsetLeft - row.clientWidth / 2 + active.clientWidth / 2;
    }
  }, [now]);

  return (
    <nav className="stepper" aria-label="Your progress">
      <p className="summary">
        Step {now} of {STEPS.length}: {STEPS[now - 1]}
      </p>
      <ol ref={list}>
        {STEPS.map((label, i) => {
          const n = i + 1;
          const href = hrefFor(n, planId);
          return (
            <li
              key={label}
              aria-current={n === now ? "step" : undefined}
              className={n < now ? "done" : undefined}
            >
              {href && n !== now ? <a href={href}>{n}. {label}</a> : <span>{n}. {label}</span>}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
