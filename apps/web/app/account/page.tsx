import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import DeleteAccount from "./DeleteAccount";

export const dynamic = "force-dynamic";

export default async function Account() {
  if (!(await cookies()).get("session")) redirect("/signin");
  return (
    <>
      <h1>Your account</h1>
      <DeleteAccount />
    </>
  );
}
