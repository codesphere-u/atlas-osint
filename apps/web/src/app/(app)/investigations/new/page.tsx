import { Suspense } from "react";
import { InvestigationForm } from "@/components/InvestigationForm";
import { PageHeader, Spinner } from "@/components/ui";

export const metadata = { title: "New investigation" };

export default function NewInvestigationPage() {
  return (
    <>
      <PageHeader
        title="New investigation"
        subtitle="Every investigation records its purpose, legal basis, scope and sharing level. Profiling individuals requires consent or self-investigation."
      />
      <Suspense fallback={<Spinner />}>
        <InvestigationForm />
      </Suspense>
    </>
  );
}
