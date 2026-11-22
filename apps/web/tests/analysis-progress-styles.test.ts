import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const styles = readFileSync("app/globals.css", "utf8");

describe("analysis progress styles", () => {
  it("does not draw a divider above the analysis progress panel", () => {
    const panelRule = styles.match(/\.analysis-progress-panel\s*\{[^}]*\}/)?.[0];

    expect(panelRule).toBeDefined();
    expect(panelRule).not.toContain("border-top");
  });
});
