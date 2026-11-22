import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const styles = readFileSync("app/globals.css", "utf8");

describe("account authentication styles", () => {
  it("keeps the selected warm-paper design in system dark mode", () => {
    const pageRule = styles.match(/\.account-auth-page\s*\{[^}]*\}/)?.[0];

    expect(pageRule).toBeDefined();
    expect(pageRule).toContain("color-scheme: light");
    expect(pageRule).toContain("--paper: #f7f3eb");
    expect(pageRule).toContain("--accent: #9b4e32");
  });

  it("places the brand message low in the upper section like the selected mock", () => {
    expect(styles).toMatch(/\.account-auth-intro\s*\{[^}]*padding:\s*115px 24px 25px;/);
    expect(styles).toMatch(/\.account-auth-intro h1\s*\{[^}]*clamp\(42px, 4vw, 60px\)/);
  });

  it("adapts the account settings page to system dark mode", () => {
    const marker = "@media (prefers-color-scheme: dark) {\n  .account-settings-page";
    const start = styles.indexOf(marker);
    const darkRule = start >= 0 ? styles.slice(start, styles.indexOf("\n}", start) + 2) : undefined;

    expect(darkRule).toBeDefined();
    expect(darkRule).toContain("--paper: #191816");
    expect(darkRule).toContain("--ink: #ede6d9");
    expect(darkRule).toContain("color-scheme: dark");
    expect(darkRule).toContain("background: rgba(36,33,29,.72)");
  });
});
