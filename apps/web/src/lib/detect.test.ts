import { describe, expect, it } from "vitest";
import { detectIdentifier } from "./detect";

describe("detectIdentifier", () => {
  it.each([
    ["someone@example.org", "email"],
    ["https://example.com/x", "url"],
    ["93.184.216.34", "ip"],
    ["2606:4700::1111", "ip"],
    ["+44 20 7946 0958", "phone"],
    ["example.co.uk", "domain"],
    ["Ada Lovelace", "name"],
    ["Siemens AG", "organization"],
    ["Example Corp.", "organization"],
    ["@octocat", "username"],
  ])("%s -> %s", (input, type) => {
    expect(detectIdentifier(input)?.type).toBe(type);
  });
  it("rejects junk", () => {
    expect(detectIdentifier("   ")).toBeNull();
    expect(detectIdentifier("<script>")).toBeNull();
    expect(detectIdentifier("999.1.1.1")?.type).not.toBe("ip");
  });
  it("strips @ from handles", () => {
    expect(detectIdentifier("@octocat")?.value).toBe("octocat");
  });
});
