"use client";

import { useEffect, useMemo, useRef, useState, type PointerEvent as RPointerEvent, type WheelEvent } from "react";
import { initialPositions, simulate, type LayoutNode } from "@/lib/graph-layout";
import { humanize, pct } from "@/lib/format";
import type { Graph, GraphNode } from "@/lib/types";

const W = 960;
const H = 640;
const KIND_COLOR: Record<string, string> = {
  account: "#5b9cff",
  person: "#c084fc",
  organization: "#f59e0b",
  domain: "#34d399",
  ip: "#22d3ee",
  url: "#94a3b8",
  email: "#f472b6",
  phone: "#fb923c",
  document: "#a3e635",
  publication: "#e879f9",
  handle: "#ffffff",
  name_query: "#ffffff",
  organization_query: "#ffffff",
};

export function EntityGraph({ graph, onSelect, selectedId }: { graph: Graph; onSelect: (n: GraphNode | null) => void; selectedId?: string }) {
  const layout = useMemo(() => {
    const subject = graph.nodes.find((n) => n.is_subject)?.id;
    const nodes = initialPositions(graph.nodes.map((n) => n.id), W, H, subject);
    const s = nodes.find((n) => n.id === subject);
    if (s) s.fixed = true;
    return simulate(nodes, graph.edges.map((e) => ({ source: e.source_entity_id, target: e.target_entity_id })), W, H);
  }, [graph]);
  const [pos, setPos] = useState<Record<string, LayoutNode>>({});
  const [view, setView] = useState({ x: 0, y: 0, k: 1 });
  const [hoverEdge, setHoverEdge] = useState<string | null>(null);
  const drag = useRef<{ id?: string; panX?: number; panY?: number; startX: number; startY: number } | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  useEffect(() => setPos(Object.fromEntries(layout.map((n) => [n.id, { ...n }]))), [layout]);
  const byId = useMemo(() => new Map(graph.nodes.map((n) => [n.id, n])), [graph]);

  function toSvg(e: { clientX: number; clientY: number }) {
    const rect = svgRef.current!.getBoundingClientRect();
    return { x: ((e.clientX - rect.left) / rect.width) * W, y: ((e.clientY - rect.top) / rect.height) * H };
  }
  function onPointerDown(e: RPointerEvent, id?: string) {
    e.stopPropagation();
    (e.target as Element).setPointerCapture?.(e.pointerId);
    const p = toSvg(e);
    drag.current = id ? { id, startX: p.x, startY: p.y } : { panX: view.x, panY: view.y, startX: p.x, startY: p.y };
  }
  function onPointerMove(e: RPointerEvent) {
    if (!drag.current) return;
    const p = toSvg(e);
    const d = drag.current;
    if (d.id) {
      const x = (p.x - view.x) / view.k;
      const y = (p.y - view.y) / view.k;
      setPos((prev) => ({ ...prev, [d.id!]: { ...prev[d.id!]!, x, y } }));
    } else {
      setView((v) => ({ ...v, x: (d.panX ?? 0) + (p.x - d.startX), y: (d.panY ?? 0) + (p.y - d.startY) }));
    }
  }
  function onWheel(e: WheelEvent) {
    const p = toSvg(e);
    const k = Math.max(0.3, Math.min(3, view.k * (e.deltaY < 0 ? 1.1 : 0.9)));
    setView((v) => ({ k, x: p.x - ((p.x - v.x) / v.k) * k, y: p.y - ((p.y - v.y) / v.k) * k }));
  }

  return (
    <div className="relative overflow-hidden rounded-lg border border-line bg-ink-900">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        className="h-[60vh] min-h-[360px] w-full touch-none select-none"
        role="img"
        aria-label={`Entity relationship graph with ${graph.nodes.length} entities and ${graph.edges.length} relationships`}
        onPointerDown={(e) => onPointerDown(e)}
        onPointerMove={onPointerMove}
        onPointerUp={() => (drag.current = null)}
        onWheel={onWheel}
        onClick={() => onSelect(null)}
      >
        <defs>
          <marker id="arrow" viewBox="0 0 10 10" refX="22" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" fill="#475569" />
          </marker>
        </defs>
        <g transform={`translate(${view.x},${view.y}) scale(${view.k})`}>
          {graph.edges.map((e) => {
            const s = pos[e.source_entity_id];
            const t = pos[e.target_entity_id];
            if (!s || !t) return null;
            const active = hoverEdge === e.id || selectedId === e.source_entity_id || selectedId === e.target_entity_id;
            return (
              <g key={e.id} onPointerEnter={() => setHoverEdge(e.id)} onPointerLeave={() => setHoverEdge(null)}>
                <line x1={s.x} y1={s.y} x2={t.x} y2={t.y} stroke="transparent" strokeWidth={10} />
                <line
                  x1={s.x} y1={s.y} x2={t.x} y2={t.y}
                  stroke={active ? "#93c5fd" : e.evidence_kind === "inference" ? "#64748b" : "#94a3b8"}
                  strokeOpacity={active ? 1 : 0.55}
                  strokeWidth={1 + e.confidence * 1.5}
                  strokeDasharray={e.evidence_kind === "inference" ? "5 4" : undefined}
                  markerEnd="url(#arrow)"
                />
                {active && (
                  <text x={(s.x + t.x) / 2} y={(s.y + t.y) / 2 - 4} textAnchor="middle" className="fill-slate-200 text-[10px]">
                    {humanize(e.type)} · {pct(e.confidence)}
                  </text>
                )}
              </g>
            );
          })}
          {graph.nodes.map((n) => {
            const p = pos[n.id];
            if (!p) return null;
            const r = n.is_subject ? 16 : 8 + Math.min(6, n.finding_ids.length);
            const selected = selectedId === n.id;
            return (
              <g
                key={n.id}
                transform={`translate(${p.x},${p.y})`}
                tabIndex={0}
                role="button"
                aria-label={`${humanize(n.kind)} ${n.label}`}
                className="cursor-pointer focus:outline-none"
                onPointerDown={(e) => onPointerDown(e, n.id)}
                onClick={(e) => { e.stopPropagation(); onSelect(byId.get(n.id) ?? null); }}
                onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onSelect(byId.get(n.id) ?? null); }}
              >
                <circle r={r + (selected ? 4 : 0)} fill={KIND_COLOR[n.kind] ?? "#94a3b8"} fillOpacity={n.is_subject ? 0.95 : 0.25 + n.confidence * 0.6}
                  stroke={selected ? "#fff" : KIND_COLOR[n.kind] ?? "#94a3b8"} strokeWidth={selected ? 2.5 : 1.5} />
                <text y={r + 13} textAnchor="middle" className="pointer-events-none fill-slate-300 text-[10px]">
                  {n.label.length > 28 ? `${n.label.slice(0, 27)}…` : n.label}
                </text>
              </g>
            );
          })}
        </g>
      </svg>
      <div className="pointer-events-none absolute bottom-2 left-2 flex flex-wrap gap-2 text-[10px] text-muted">
        <span>— direct evidence</span><span>- - inference</span><span>drag · scroll to zoom · click for details</span>
      </div>
    </div>
  );
}

export const GRAPH_KIND_COLOR = KIND_COLOR;
