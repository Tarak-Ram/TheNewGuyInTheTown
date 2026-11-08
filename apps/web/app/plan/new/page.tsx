import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import Stepper from "../../../components/Stepper";
import PlanForm from "../PlanForm";

export const dynamic = "force-dynamic";

export default async function NewPlan() {
  if (!(await cookies()).get("session")) redirect("/signin");
  return (
    <>
      <Stepper current={2} />
      <h1>Tell us about your move</h1>
      <p>We use this to find areas in Hyderabad that suit you.</p>
      <PlanForm demoHint={process.env.DEMO_MODE === "true"} />
    </>
  );
}
