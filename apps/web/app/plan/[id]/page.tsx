import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import RankedAreas from "./RankedAreas";

export const dynamic = "force-dynamic";

export default async function PlanPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!(await cookies()).get("session")) redirect("/signin");
  return (
    <>
      <h1>Areas that suit you</h1>
      <RankedAreas planId={id} />
    </>
  );
}
