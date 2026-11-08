import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import Stepper from "../../../components/Stepper";
import DemoCall from "./DemoCall";

export const dynamic = "force-dynamic";

export default async function CallPage({ params }: { params: Promise<{ callId: string }> }) {
  const { callId } = await params;
  if (!(await cookies()).get("session")) redirect("/signin");
  const gatewayUrl = process.env.GATEWAY_PUBLIC_URL ?? "ws://localhost:8011";
  return (
    <>
      <Stepper current={4} />
      <h1>Demo call</h1>
      <p
        role="note"
        style={{ background: "#e8f0fe", border: "1px solid #9bb8f0", padding: 12, borderRadius: 8 }}
      >
        <strong>This is a demo owner.</strong> You play the PG owner using your own microphone. No
        real phone is called and no real PG owner is contacted.
      </p>
      <DemoCall callId={callId} gatewayUrl={gatewayUrl} />
    </>
  );
}
