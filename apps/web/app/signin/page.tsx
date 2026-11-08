import Stepper from "../../components/Stepper";
import DemoSignIn from "./DemoSignIn";
import GoogleButton from "./GoogleButton";

export const dynamic = "force-dynamic";

export default function SignIn() {
  const clientId = process.env.GOOGLE_CLIENT_ID;
  const demo = process.env.DEMO_MODE === "true";
  return (
    <>
      <Stepper current={1} />
      <h1>Sign in</h1>
      {clientId && <GoogleButton clientId={clientId} />}
      {demo && (
        <section style={{ marginTop: 16 }}>
          <p>For the demo you can skip Google and use a sample account.</p>
          <DemoSignIn />
        </section>
      )}
      {!clientId && !demo && (
        <p>Google sign-in is not set up yet. Add GOOGLE_CLIENT_ID to your .env file.</p>
      )}
    </>
  );
}
