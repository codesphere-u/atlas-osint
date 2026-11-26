import { describe, expect, it } from "vitest";
import { initialPositions, simulate } from "./graph-layout";

describe("graph layout", () => {
  it("keeps nodes inside the canvas and separates them", () => {
    const ids = ["s", "a", "b", "c", "d"];
    const nodes = simulate(
      initialPositions(ids, 800, 600, "s"),
      ids.slice(1).map((id) => ({ source: "s", target: id })),
      800,
      600,
    );
    for (const n of nodes) {
      expect(n.x).toBeGreaterThanOrEqual(30);
      expect(n.x).toBeLessThanOrEqual(770);
      expect(n.y).toBeGreaterThanOrEqual(30);
      expect(n.y).toBeLessThanOrEqual(570);
    }
    const [a, b] = [nodes[1]!, nodes[2]!];
    expect(Math.hypot(a.x - b.x, a.y - b.y)).toBeGreaterThan(20);
  });

  it("is deterministic", () => {
    const run = () =>
      simulate(initialPositions(["x", "y"], 400, 400), [{ source: "x", target: "y" }], 400, 400).map((n) => [
        Math.round(n.x),
        Math.round(n.y),
      ]);
    expect(run()).toEqual(run());
  });
});
