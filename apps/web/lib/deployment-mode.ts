export type DeploymentMode = "local" | "cloud";

export function deploymentMode(
  value = process.env.BOOKTHINKING_DEPLOYMENT_MODE,
): DeploymentMode {
  if (value === undefined || value === "" || value === "local") return "local";
  if (value === "cloud") return "cloud";
  throw new Error("BOOKTHINKING_DEPLOYMENT_MODE must be local or cloud");
}

export function isCloudDeployment(value?: string): boolean {
  return deploymentMode(value) === "cloud";
}
