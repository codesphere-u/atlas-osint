"use client";

import { useUser } from "@/components/AppShell";
import { GraphWorkspace } from "@/components/GraphWorkspace";
import { useInvestigation } from "@/components/InvestigationContext";
import { SkeletonRows } from "@/components/ui";

export default function GraphPage() {
  const { inv } = useInvestigation();
  const user = useUser();
  const owner = !!user && (user.role === "admin" || (user.role === "analyst" && user.id === inv.created_by));
  if (inv.status !== "completed") return <SkeletonRows rows={4} />;
  return <GraphWorkspace url={`/api/v1/investigations/${inv.id}/graph`} pivotFrom={owner ? inv.id : undefined} />;
}
