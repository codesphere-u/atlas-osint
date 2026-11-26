import { InvestigationProvider } from "@/components/InvestigationContext";

export default function InvestigationLayout({ children }: { children: React.ReactNode }) {
  return <InvestigationProvider>{children}</InvestigationProvider>;
}
