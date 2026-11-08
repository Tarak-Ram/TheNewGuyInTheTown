import type { PlanOut } from "@schemas";
import { cookies } from "next/headers";
import { notFound, redirect } from "next/navigation";
import PlanForm from "../../PlanForm";

export const dynamic = "force-dynamic";

export default async function EditPlan({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const token = (await cookies()).get("session")?.value;
  if (!token) redirect("/signin");

  const res = await fetch(`${process.env.API_URL ?? "http://localhost:8010"}/v1/plans/${id}`, {
    headers: { authorization: `Bearer ${token}` },
    cache: "no-store",
  }).catch(() => null);
  if (res?.status === 401) redirect("/signin");
  if (!res || !res.ok) notFound();
  const plan = (await res.json()) as PlanOut;

  return (
    <>
      <h1>Edit your details</h1>
      <PlanForm planId={id} initial={plan} />
    </>
  );
}
