import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import ComparisonTable from "./ComparisonTable";

export const dynamic = "force-dynamic";

export default async function ComparisonPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!(await cookies()).get("session")) redirect("/signin");
  return (
    <>
      <h1>Compare PGs</h1>
      <ComparisonTable planId={id} />
      <p>
        <a href={`/plan/${id}/agreement`}>Check an agreement</a> |{" "}
        <a href={`/plan/${id}/calls`}>Call more PGs</a> | <a href={`/plan/${id}`}>Back to areas</a>
      </p>
    </>
  );
}
