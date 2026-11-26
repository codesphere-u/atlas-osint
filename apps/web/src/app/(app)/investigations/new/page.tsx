import { InvestigationForm } from "@/components/InvestigationForm";
import { PageHeader } from "@/components/ui";

export const metadata = { title: "New investigation" };

export default function NewInvestigationPage() {
  return (
    <>
      <PageHeader
        title="New investigation"
        subtitle="Every investigation records its purpose, legal basis and scope. Profiling individuals requires consent or self-investigation."
      />
      <InvestigationForm />
    </>
  );
}
