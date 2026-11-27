/** Deterministic force-directed layout (no external dependencies). */
export interface LayoutNode {
  id: string;
  x: number;
  y: number;
  vx: number;
  vy: number;
  fixed?: boolean;
}

export interface LayoutEdge {
  source: string;
  target: string;
}

export function initialPositions(ids: string[], width: number, height: number, centerId?: string): LayoutNode[] {
  const r = Math.min(width, height) * 0.35;
  const others = ids.filter((id) => id !== centerId);
  return ids.map((id) => {
    if (id === centerId) return { id, x: width / 2, y: height / 2, vx: 0, vy: 0 };
    const i = others.indexOf(id);
    const angle = (2 * Math.PI * i) / Math.max(1, others.length);
    return { id, x: width / 2 + r * Math.cos(angle), y: height / 2 + r * Math.sin(angle), vx: 0, vy: 0 };
  });
}

export function simulate(
  nodes: LayoutNode[],
  edges: LayoutEdge[],
  width: number,
  height: number,
  iterations = 300,
): LayoutNode[] {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const k = Math.sqrt((width * height) / Math.max(1, nodes.length)) * 0.6;
  for (let it = 0; it < iterations; it++) {
    const cooling = 1 - it / iterations;
    for (const a of nodes) {
      for (const b of nodes) {
        if (a === b) continue;
        const dx = a.x - b.x || 0.01;
        const dy = a.y - b.y || 0.01;
        const dist2 = dx * dx + dy * dy;
        const force = (k * k) / Math.max(dist2, 1);
        a.vx += dx * force * 0.02;
        a.vy += dy * force * 0.02;
      }
    }
    for (const e of edges) {
      const s = byId.get(e.source);
      const t = byId.get(e.target);
      if (!s || !t) continue;
      const dx = t.x - s.x;
      const dy = t.y - s.y;
      const dist = Math.sqrt(dx * dx + dy * dy) || 1;
      const force = ((dist - k) / dist) * 0.05;
      s.vx += dx * force;
      s.vy += dy * force;
      t.vx -= dx * force;
      t.vy -= dy * force;
    }
    for (const n of nodes) {
      n.vx += (width / 2 - n.x) * 0.002;
      n.vy += (height / 2 - n.y) * 0.002;
      if (!n.fixed) {
        n.x += Math.max(-20, Math.min(20, n.vx)) * cooling;
        n.y += Math.max(-20, Math.min(20, n.vy)) * cooling;
      }
      n.vx *= 0.6;
      n.vy *= 0.6;
      n.x = Math.max(30, Math.min(width - 30, n.x));
      n.y = Math.max(30, Math.min(height - 30, n.y));
    }
  }
  return nodes;
}

/** Radial layout: subjects in the centre, other nodes on rings by graph distance (BFS) from a subject. */
export function radialLayout(ids: string[], edges: LayoutEdge[], width: number, height: number, centers: string[]): LayoutNode[] {
  const adj = new Map<string, Set<string>>(ids.map((id) => [id, new Set()]));
  for (const e of edges) {
    adj.get(e.source)?.add(e.target);
    adj.get(e.target)?.add(e.source);
  }
  const depth = new Map<string, number>();
  const queue = centers.filter((c) => adj.has(c));
  queue.forEach((c) => depth.set(c, 0));
  while (queue.length) {
    const cur = queue.shift()!;
    for (const n of adj.get(cur) ?? []) {
      if (!depth.has(n)) {
        depth.set(n, (depth.get(cur) ?? 0) + 1);
        queue.push(n);
      }
    }
  }
  const maxDepth = Math.max(1, ...depth.values());
  for (const id of ids) if (!depth.has(id)) depth.set(id, maxDepth + 1);
  const rings = new Map<number, string[]>();
  for (const id of [...ids].sort()) rings.set(depth.get(id)!, [...(rings.get(depth.get(id)!) ?? []), id]);
  const ringCount = Math.max(...rings.keys());
  const maxR = Math.min(width, height) / 2 - 40;
  const out: LayoutNode[] = [];
  for (const [d, members] of rings) {
    const r = d === 0 ? (members.length > 1 ? 40 : 0) : (d / ringCount) * maxR;
    members.forEach((id, i) => {
      const a = (2 * Math.PI * i) / members.length + d * 0.35;
      out.push({ id, x: width / 2 + r * Math.cos(a), y: height / 2 + r * Math.sin(a), vx: 0, vy: 0 });
    });
  }
  return out;
}

/** Ids of a node and its direct neighbours. */
export function neighbourhood(id: string, edges: LayoutEdge[]): Set<string> {
  const out = new Set([id]);
  for (const e of edges) {
    if (e.source === id) out.add(e.target);
    if (e.target === id) out.add(e.source);
  }
  return out;
}
