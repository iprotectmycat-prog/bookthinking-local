import { notFound } from "next/navigation";

import { LocalModelSettings } from "../../components/LocalModelSettings";
import { isCloudDeployment } from "../../lib/deployment-mode";

export default function SettingsPage() {
  if (isCloudDeployment()) notFound();
  return <LocalModelSettings />;
}
