import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import CallsPlanner from "./CallsPlanner";

export const dynamic = "force-dynamic";

export default async function CallsPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!(await cookies()).get("session")) redirect("/signin");
  return (
    <>
      <h1>Compare PGs by voice</h1>
      <CallsPlanner planId={id} />
    </>
  );
}
