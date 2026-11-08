import type { PlanOut, UserOut } from "@schemas";
import { cookies } from "next/headers";

export const dynamic = "force-dynamic";

type Session =
  | { kind: "signed_out" }
  | { kind: "unavailable" }
  | { kind: "signed_in"; user: UserOut; plans: PlanOut[] };

async function loadSession(): Promise<Session> {
  const token = (await cookies()).get("session")?.value;
  if (!token) return { kind: "signed_out" };
  const base = process.env.API_URL ?? "http://localhost:8010";
  const headers = { authorization: `Bearer ${token}` };
  try {
    const me = await fetch(`${base}/v1/me`, { headers, cache: "no-store" });
    if (me.status === 401) return { kind: "signed_out" }; // expired session
    if (!me.ok) return { kind: "unavailable" };
    const plans = await fetch(`${base}/v1/plans`, { headers, cache: "no-store" });
    return {
      kind: "signed_in",
      user: (await me.json()) as UserOut,
      plans: plans.ok ? ((await plans.json()) as PlanOut[]) : [],
    };
  } catch {
    return { kind: "unavailable" };
  }
}

export default async function Home() {
  const session = await loadSession();
  return (
    <>
      <h1>Moving to Hyderabad? Find a place without the guesswork.</h1>
      <p>
        We help you choose an area, compare PGs by voice call, and check your rental agreement
        before you pay. It takes about ten minutes.
      </p>
      <ol>
        <li><strong>Pick an area</strong> that suits your office, budget and needs.</li>
        <li><strong>Compare PGs</strong> from a voice call, with rent, deposit and rules in one table.</li>
        <li><strong>Check the agreement</strong> and see which clauses to question.</li>
      </ol>

      {session.kind === "unavailable" && (
        <p role="alert" className="error">
          We cannot reach the service right now. Please try again in a minute.
        </p>
      )}

      {session.kind === "signed_out" && (
        <p><a className="button" href="/signin">Get started</a></p>
      )}

      {session.kind === "signed_in" && (
        <section>
          <p>Signed in as {session.user.email}.</p>
          {session.plans.length > 0 ? (
            <>
              {session.plans.slice(0, 3).map((p, i) => (
                <div className="card" key={p.id}>
                  <strong>{i === 0 ? "Your latest plan" : "Earlier plan"}</strong>
                  <p style={{ margin: "4px 0" }}>
                    {p.office_address}. Budget Rs {p.budget_min.toLocaleString("en-IN")} to Rs{" "}
                    {p.budget_max.toLocaleString("en-IN")}.
                  </p>
                  <a className={i === 0 ? "button" : "button secondary"} href={`/plan/${p.id}`}>
                    Continue this plan
                  </a>
                </div>
              ))}
              <p><a className="button secondary" href="/plan/new">Start a new plan</a></p>
            </>
          ) : (
            <p><a className="button" href="/plan/new">Start my move plan</a></p>
          )}
        </section>
      )}
    </>
  );
}
