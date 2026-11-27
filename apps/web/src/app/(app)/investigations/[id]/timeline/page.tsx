"use client";

import { useInvestigation } from "@/components/InvestigationContext";
import { TimelineView } from "@/components/TimelineView";
import { SkeletonRows } from "@/components/ui";
import { useApi } from "@/lib/hooks";
import type { TimelineEvent } from "@/lib/types";

export default function TimelinePage() {
  const { inv } = useInvestigation();
  const { data } = useApi<TimelineEvent[]>(inv.status === "completed" ? `/api/v1/investigations/${inv.id}/timeline` : null);
  if (inv.status !== "completed" || !data) return <SkeletonRows rows={5} />;
  return <TimelineView events={data} />;
}
