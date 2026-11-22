import { expect, it } from "vitest";

import { deploymentMode, isCloudDeployment } from "../lib/deployment-mode";

it("defaults to the single-user local experience", () => {
  expect(deploymentMode()).toBe("local");
  expect(deploymentMode("")).toBe("local");
  expect(deploymentMode("local")).toBe("local");
  expect(isCloudDeployment("local")).toBe(false);
});

it("recognizes the explicit cloud mode", () => {
  expect(deploymentMode("cloud")).toBe("cloud");
  expect(isCloudDeployment("cloud")).toBe(true);
});

it("rejects invalid deployment modes instead of silently changing behavior", () => {
  expect(() => deploymentMode("remote")).toThrow(
    "BOOKTHINKING_DEPLOYMENT_MODE must be local or cloud",
  );
});
