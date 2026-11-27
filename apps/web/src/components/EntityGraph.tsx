"use client";

import {
  AtSign, Building2, Download, FileText, Fingerprint, Globe, Image as ImageIcon, Link2, Mail, Maximize, Minus, Network,
  Newspaper, Orbit, Phone, Plus, Search, Server, UserRound,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ComponentType, type PointerEvent as RPointerEvent, type WheelEvent } from "react";
import { initialPositions, neighbourhood, radialLayout, simulate, type LayoutNode } from "@/lib/graph-layout";
import { humanize, pct } from "@/lib/format";
import type { Graph, GraphNode } from "@/lib/types";
import { cx } from "./ui";

const W = 1000;
const H = 660;

/* Kind colours: the three most common kinds use the validated categorical slots 1-3; the rest share a neutral
   tone and are distinguished by their icon and label (identity is never colour-alone). */
const KIND: Record<string, { color: string; icon: ComponentType<{ className?: string; x?: number; y?: number; width?: number; height?: number }> }> = {
  account: { color: "#338ced", icon: AtSign },
  domain: { color: "#00a888", icon: Globe },
  organization: { color: "#e76624", icon: Building2 },
  person: { color: "#9887ef", icon: UserRound },
  ip: { color: "#64748b", icon: Server },
  url: { color: "#64748b", icon: Link2 },
  email: { color: "#64748b", icon: Mail },
  phone: { color: "#64748b", icon: Phone },
  document: { color: "#64748b", icon: FileText },
  publication: { color: "#64748b", icon: Newspaper },
  handle: { color: "#e2e8f0", icon: Fingerprint },
  name_query: { color: "#e2e8f0", icon: Fingerprint },
  organization_query: { color: "#e2e8f0", icon: Fingerprint },
};
const kindOf = (k: string) => KIND[k] ?? { color: "#64748b", icon: Fingerprint };

export function EntityGraph({ graph, onSelect, selectedId }: { graph: Graph; onSelect: (n: GraphNode | null) => void; selectedId?: string }) {
  const [layoutMode, setLayoutMode] = useState<"force" | "radial">("force");
  const [hiddenKinds, setHiddenKinds] = useState<Set<string>>(new Set());
  const [showInference, setShowInference] = useState(true);
  const [showLabels, setShowLabels] = useState(true);
  const [focus, setFocus] = useState(false);
  const [query, setQuery] = useState("");
  const kinds = useMemo(() => [...new Set(graph.nodes.map((n) => n.kind))].sort(), [graph]);

  const nodes = useMemo(() => graph.nodes.filter((n) => n.is_subject || !hiddenKinds.has(n.kind)), [graph, hiddenKinds]);
  const nodeIds = useMemo(() => new Set(nodes.map((n) => n.id)), [nodes]);
  const edges = useMemo(() => graph.edges.filter((e) => nodeIds.has(e.source_entity_id) && nodeIds.has(e.target_entity_id) &&
    (showInference || e.evidence_kind === "direct")), [graph, nodeIds, showInference]);
  const layoutEdges = useMemo(() => edges.map((e) => ({ source: e.source_entity_id, target: e.target_entity_id })), [edges]);

  const layout = useMemo(() => {
    const subjects = nodes.filter((n) => n.is_subject).map((n) => n.id);
    if (layoutMode === "radial") return radialLayout(nodes.map((n) => n.id), layoutEdges, W, H, subjects);
    const init = initialPositions(nodes.map((n) => n.id), W, H, subjects.length === 1 ? subjects[0] : undefined);
    const s = subjects.length === 1 ? init.find((n) => n.id === subjects[0]) : undefined;
    if (s) s.fixed = true;
    return simulate(init, layoutEdges, W, H);
  }, [nodes, layoutEdges, layoutMode]);

  const [pos, setPos] = useState<Record<string, LayoutNode>>({});
  const [view, setView] = useState({ x: 0, y: 0, k: 1 });
  const [hoverEdge, setHoverEdge] = useState<string | null>(null);
  const drag = useRef<{ id?: string; panX?: number; panY?: number; startX: number; startY: number } | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  useEffect(() => setPos(Object.fromEntries(layout.map((n) => [n.id, { ...n }]))), [layout]);

  const byId = useMemo(() => new Map(graph.nodes.map((n) => [n.id, n])), [graph]);
  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? new Set(nodes.filter((n) => `${n.label} ${n.identifiers.join(" ")}`.toLowerCase().includes(q)).map((n) => n.id)) : null;
  }, [query, nodes]);
  const focusSet = focus && selectedId ? neighbourhood(selectedId, layoutEdges) : null;
  const dimmed = (id: string) => (focusSet ? !focusSet.has(id) : matches ? !matches.has(id) : false);

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
      setPos((prev) => (prev[d.id!] ? { ...prev, [d.id!]: { ...prev[d.id!]!, x, y } } : prev));
    } else {
      setView((v) => ({ ...v, x: (d.panX ?? 0) + (p.x - d.startX), y: (d.panY ?? 0) + (p.y - d.startY) }));
    }
  }
  function zoom(factor: number, cx0 = W / 2, cy0 = H / 2) {
    setView((v) => {
      const k = Math.max(0.3, Math.min(3, v.k * factor));
      return { k, x: cx0 - ((cx0 - v.x) / v.k) * k, y: cy0 - ((cy0 - v.y) / v.k) * k };
    });
  }
  function onWheel(e: WheelEvent) {
    const p = toSvg(e);
    zoom(e.deltaY < 0 ? 1.1 : 0.9, p.x, p.y);
  }
  function fit() {
    const pts = Object.values(pos);
    if (!pts.length) return;
    const xs = pts.map((p) => p.x), ys = pts.map((p) => p.y);
    const minX = Math.min(...xs) - 40, maxX = Math.max(...xs) + 40, minY = Math.min(...ys) - 40, maxY = Math.max(...ys) + 40;
    const k = Math.max(0.3, Math.min(2.5, Math.min(W / (maxX - minX), H / (maxY - minY))));
    setView({ k, x: (W - (minX + maxX) * k) / 2, y: (H - (minY + maxY) * k) / 2 });
  }
  function exportSvg(): string {
    const clone = svgRef.current!.cloneNode(true) as SVGSVGElement;
    clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    clone.style.background = "#0b1120";
    return new XMLSerializer().serializeToString(clone);
  }
  function download(name: string, href: string) {
    const a = document.createElement("a");
    a.href = href;
    a.download = name;
    a.click();
  }
  function saveSvg() {
    download("atlas-graph.svg", URL.createObjectURL(new Blob([exportSvg()], { type: "image/svg+xml" })));
  }
  function savePng() {
    const img = new window.Image();
    img.onload = () => {
      const c = document.createElement("canvas");
      c.width = W * 2;
      c.height = H * 2;
      const ctx = c.getContext("2d")!;
      ctx.fillStyle = "#0b1120";
      ctx.fillRect(0, 0, c.width, c.height);
      ctx.drawImage(img, 0, 0, c.width, c.height);
      download("atlas-graph.png", c.toDataURL("image/png"));
    };
    img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(exportSvg())}`;
  }

  const tool = "inline-flex h-8 items-center gap-1.5 rounded-md border border-line bg-ink-900 px-2 text-xs text-slate-300 hover:bg-ink-700";
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2" role="toolbar" aria-label="Graph tools">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted" aria-hidden />
          <input aria-label="Find entity" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Find entity"
            className="h-8 w-40 rounded-md border border-line bg-ink-900 pl-7 pr-2 text-xs text-slate-100 placeholder:text-slate-500 focus:border-accent focus:outline-none" />
        </div>
        <button className={tool} onClick={() => zoom(1.2)} aria-label="Zoom in"><Plus className="h-3.5 w-3.5" /></button>
        <button className={tool} onClick={() => zoom(1 / 1.2)} aria-label="Zoom out"><Minus className="h-3.5 w-3.5" /></button>
        <button className={tool} onClick={fit}><Maximize className="h-3.5 w-3.5" />Fit</button>
        <button className={cx(tool, layoutMode === "force" && "border-accent text-white")} onClick={() => setLayoutMode("force")} aria-pressed={layoutMode === "force"}>
          <Network className="h-3.5 w-3.5" />Force</button>
        <button className={cx(tool, layoutMode === "radial" && "border-accent text-white")} onClick={() => setLayoutMode("radial")} aria-pressed={layoutMode === "radial"}>
          <Orbit className="h-3.5 w-3.5" />Radial</button>
        <label className={tool}><input type="checkbox" checked={showInference} onChange={(e) => setShowInference(e.target.checked)} />Inference edges</label>
        <label className={tool}><input type="checkbox" checked={showLabels} onChange={(e) => setShowLabels(e.target.checked)} />Labels</label>
        <label className={cx(tool, !selectedId && "opacity-50")} title="Dim everything except the selected entity and its neighbours">
          <input type="checkbox" disabled={!selectedId} checked={focus} onChange={(e) => setFocus(e.target.checked)} />Focus</label>
        <span className="ml-auto flex gap-2">
          <button className={tool} onClick={saveSvg}><Download className="h-3.5 w-3.5" />SVG</button>
          <button className={tool} onClick={savePng}><ImageIcon className="h-3.5 w-3.5" />PNG</button>
        </span>
      </div>
      <div className="flex flex-wrap gap-1.5" aria-label="Entity kinds">
        {kinds.map((k) => {
          const { color, icon: Icon } = kindOf(k);
          const hidden = hiddenKinds.has(k);
          const count = graph.nodes.filter((n) => n.kind === k).length;
          return (
            <button key={k} aria-pressed={!hidden}
              onClick={() => setHiddenKinds((s) => { const n = new Set(s); if (n.has(k)) n.delete(k); else n.add(k); return n; })}
              className={cx("flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px]", hidden ? "border-line text-muted line-through" : "border-line text-slate-200")}>
              <span className="h-2 w-2 rounded-full" style={{ background: color }} aria-hidden /><Icon className="h-3 w-3" />{humanize(k)}
              <span className="font-mono text-muted">{count}</span>
            </button>
          );
        })}
      </div>
      <div className="relative overflow-hidden rounded-lg border border-line bg-ink-900 bg-[radial-gradient(circle_at_1px_1px,#1c2843_1px,transparent_0)] [background-size:22px_22px]">
        <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} className="h-[62vh] min-h-[380px] w-full touch-none select-none"
          role="img" aria-label={`Entity relationship graph with ${nodes.length} entities and ${edges.length} relationships`}
          onPointerDown={(e) => onPointerDown(e)} onPointerMove={onPointerMove} onPointerUp={() => (drag.current = null)}
          onWheel={onWheel} onClick={() => onSelect(null)}>
          <defs>
            <marker id="arrow" viewBox="0 0 10 10" refX="24" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
              <path d="M0,0 L10,5 L0,10 z" fill="#475569" />
            </marker>
          </defs>
          <g transform={`translate(${view.x},${view.y}) scale(${view.k})`}>
            {edges.map((e) => {
              const s = pos[e.source_entity_id];
              const t = pos[e.target_entity_id];
              if (!s || !t) return null;
              const active = hoverEdge === e.id || selectedId === e.source_entity_id || selectedId === e.target_entity_id;
              const faded = dimmed(e.source_entity_id) || dimmed(e.target_entity_id);
              return (
                <g key={e.id} onPointerEnter={() => setHoverEdge(e.id)} onPointerLeave={() => setHoverEdge(null)} opacity={faded ? 0.12 : 1}>
                  <line x1={s.x} y1={s.y} x2={t.x} y2={t.y} stroke="transparent" strokeWidth={12} />
                  <line x1={s.x} y1={s.y} x2={t.x} y2={t.y}
                    stroke={active ? "#93c5fd" : e.evidence_kind === "inference" ? "#64748b" : "#94a3b8"}
                    strokeOpacity={active ? 1 : 0.55} strokeWidth={active ? 2 : 1 + e.confidence}
                    strokeDasharray={e.evidence_kind === "inference" ? "5 4" : undefined} markerEnd="url(#arrow)" />
                  {active && (
                    <text x={(s.x + t.x) / 2} y={(s.y + t.y) / 2 - 5} textAnchor="middle" fontSize={11} fill="#e2e8f0"
                      stroke="#0b1120" strokeWidth={3} paintOrder="stroke">
                      {humanize(e.type)} · {pct(e.confidence)}
                    </text>
                  )}
                </g>
              );
            })}
            {nodes.map((n) => {
              const p = pos[n.id];
              if (!p) return null;
              const { color, icon: Icon } = kindOf(n.kind);
              const r = n.is_subject ? 18 : 11 + Math.min(5, n.finding_ids.length);
              const selected = selectedId === n.id;
              const hit = matches?.has(n.id);
              return (
                <g key={n.id} transform={`translate(${p.x},${p.y})`} tabIndex={0} role="button" aria-label={`${humanize(n.kind)} ${n.label}`}
                  className="cursor-pointer focus:outline-none" opacity={dimmed(n.id) ? 0.18 : 1}
                  onPointerDown={(e) => onPointerDown(e, n.id)}
                  onClick={(e) => { e.stopPropagation(); onSelect(byId.get(n.id) ?? null); }}
                  onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onSelect(byId.get(n.id) ?? null); }}>
                  {(selected || hit) && <circle r={r + 6} fill="none" stroke={selected ? "#ffffff" : "#5b9cff"} strokeWidth={2} />}
                  <circle r={r} fill="#0f172a" stroke={color} strokeWidth={n.is_subject ? 3 : 2} />
                  <circle r={r - 3} fill={color} fillOpacity={0.15 + n.confidence * 0.35} />
                  <Icon x={-7} y={-7} width={14} height={14} className="pointer-events-none text-slate-100" />
                  {showLabels && (
                    <text y={r + 14} textAnchor="middle" fontSize={11} fill="#cbd5e1" stroke="#0b1120" strokeWidth={3} paintOrder="stroke"
                      className="pointer-events-none">
                      {n.label.length > 30 ? `${n.label.slice(0, 29)}…` : n.label}
                    </text>
                  )}
                </g>
              );
            })}
          </g>
        </svg>
        <div className="pointer-events-none absolute bottom-2 left-2 flex flex-wrap gap-3 rounded bg-ink-950/70 px-2 py-1 text-[10px] text-muted">
          <span>── direct evidence</span><span>- - - inference</span><span>drag · scroll to zoom · click for details</span>
        </div>
      </div>
    </div>
  );
}
