import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import AgreementChecker from "./AgreementChecker";

export const dynamic = "force-dynamic";

export default async function AgreementPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!(await cookies()).get("session")) redirect("/signin");
  return (
    <>
      <h1>Check your agreement</h1>
      <AgreementChecker planId={id} />
      <p><a href={`/plan/${id}/comparison`}>Back to PG comparison</a></p>
    </>
  );
}
