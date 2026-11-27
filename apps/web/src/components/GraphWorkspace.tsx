"use client";

import { useState } from "react";
import { humanize, pct } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Graph, GraphNode } from "@/lib/types";
import { EntityGraph } from "./EntityGraph";
import { pivotTarget, PivotDialog, type PivotTarget } from "./PivotDialog";
import { Badge, Card, EmptyState, KeyValue, SkeletonRows } from "./ui";

export function GraphWorkspace({ url, pivotFrom }: { url: string; pivotFrom?: string }) {
  const [minConfidence, setMinConfidence] = useState(0);
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const [pivot, setPivot] = useState<PivotTarget | null>(null);
  const { data } = useApi<Graph>(`${url}?min_confidence=${minConfidence}`);
  if (!data) return <SkeletonRows rows={4} />;
  if (!data.nodes.length) return <EmptyState title="No entities" />;
  const labels = new Map(data.nodes.map((n) => [n.id, n.label]));
  const edgesFor = selected ? data.edges.filter((e) => e.source_entity_id === selected.id || e.target_entity_id === selected.id) : [];

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,3fr)_minmax(0,1fr)]">
      <div className="min-w-0 space-y-3">
        <EntityGraph graph={data} onSelect={setSelected} selectedId={selected?.id} />
        <label className="flex items-center gap-2 text-xs text-muted">
          Minimum confidence
          <input type="range" min={0} max={1} step={0.05} value={minConfidence} onChange={(e) => setMinConfidence(Number(e.target.value))} />
          <span className="w-10 font-mono">{pct(minConfidence)}</span>
        </label>
        {(data.name_collisions.length > 0 || data.contradictions.length > 0) && (
          <Card title="Ambiguities">
            <ul className="space-y-2 text-sm text-warn">
              {data.name_collisions.map((c, i) => <li key={`n${i}`}>{c.explanation}</li>)}
              {data.contradictions.map((c, i) => <li key={`c${i}`}>{c.explanation}</li>)}
            </ul>
          </Card>
        )}
        <details className="rounded-lg border border-line bg-ink-850 p-3 text-sm">
          <summary className="cursor-pointer text-slate-200">Relationships as a table (accessible view)</summary>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[640px] text-left text-xs">
              <thead className="text-muted"><tr><th>From</th><th>Relation</th><th>To</th><th>Evidence</th><th>Confidence</th><th>Rationale</th></tr></thead>
              <tbody className="divide-y divide-line">
                {data.edges.map((e) => (
                  <tr key={e.id}><td className="py-1">{labels.get(e.source_entity_id)}</td><td>{humanize(e.type)}</td><td>{labels.get(e.target_entity_id)}</td>
                    <td>{e.evidence_kind}</td><td className="font-mono">{pct(e.confidence)}</td><td className="text-muted">{e.rationale}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      </div>
      <Card title={selected ? selected.label : "Entity details"} className="xl:sticky xl:top-20 xl:self-start">
        {!selected ? <p className="text-sm text-muted">Select an entity to see its identifiers, attributes and relationships.</p> : (
          <div className="space-y-3 text-sm">
            <div className="flex flex-wrap gap-2">
              <Badge>{humanize(selected.kind)}</Badge>
              {selected.is_subject && <Badge className="border-accent/50 text-accent">Subject</Badge>}
              <Badge>Confidence {pct(selected.confidence)}</Badge>
              <Badge>{selected.finding_ids.length} findings</Badge>
            </div>
            {selected.identifiers.length > 0 && (
              <div>
                <div className="mb-1 text-xs text-muted">Identifiers</div>
                <ul className="space-y-1 font-mono text-xs">
                  {selected.identifiers.map((i) => {
                    const [type, ...rest] = i.split(":");
                    const target = pivotFrom && !selected.is_subject ? pivotTarget(type ?? "", rest.join(":")) : null;
                    return (
                      <li key={i} className="flex items-center justify-between gap-2 break-all">
                        <span>{i}</span>
                        {target && <button onClick={() => setPivot(target)} className="shrink-0 rounded border border-line px-1.5 font-sans text-[11px] text-accent hover:bg-accent-soft">Pivot</button>}
                      </li>
                    );
                  })}
                </ul>
              </div>
            )}
            <KeyValue data={selected.attributes} />
            <div>
              <div className="mb-1 text-xs text-muted">Relationships ({edgesFor.length})</div>
              <ul className="space-y-1 text-xs">
                {edgesFor.map((e) => (
                  <li key={e.id}>
                    {e.source_entity_id === selected.id ? "→" : "←"} {humanize(e.type)}{" "}
                    <span className="text-slate-300">{labels.get(e.source_entity_id === selected.id ? e.target_entity_id : e.source_entity_id)}</span>{" "}
                    <span className={e.evidence_kind === "inference" ? "text-warn" : "text-ok"}>({e.evidence_kind})</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        )}
      </Card>
      {pivotFrom && <PivotDialog investigationId={pivotFrom} target={pivot} onClose={() => setPivot(null)} />}
    </div>
  );
}
