import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

import { expect, it } from "vitest";

it("allows the loopback URL used to open the local app during development", () => {
  const configPath = resolve(process.cwd(), "next.config.ts");
  expect(existsSync(configPath)).toBe(true);

  const config = readFileSync(configPath, "utf8");

  expect(config).toContain('allowedDevOrigins: ["127.0.0.1"]');
});
