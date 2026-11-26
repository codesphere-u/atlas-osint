import { describe, expect, it } from "vitest";
import { ApiError } from "./api";
import { pct, safeHref } from "./format";

describe("format helpers", () => {
  it("only links http(s) URLs", () => {
    expect(safeHref("https://example.com")).toBe("https://example.com");
    expect(safeHref("javascript:alert(1)")).toBeUndefined();
    expect(safeHref("dns:example.com")).toBeUndefined();
  });
  it("formats percentages", () => {
    expect(pct(0.875)).toBe("88%");
    expect(pct(null)).toBe("—");
  });
  it("flattens API errors", () => {
    expect(new ApiError(422, { authorization: ["need consent"] }).messages).toEqual(["need consent"]);
    expect(new ApiError(422, [{ loc: ["body", "subject"], msg: "bad" }]).messages).toEqual(["subject: bad"]);
  });
});
