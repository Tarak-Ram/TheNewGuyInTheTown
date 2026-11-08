import type { ReactNode } from "react";
import Stepper from "../../../components/Stepper";

export default async function PlanLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <>
      <Stepper planId={id} />
      {children}
    </>
  );
}
