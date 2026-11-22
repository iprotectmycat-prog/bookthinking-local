import { redirect } from "next/navigation";

import { BookshelfHome } from "../../components/BookshelfHome";
import { isCloudDeployment } from "../../lib/deployment-mode";

export default function MyShelfPage() {
  if (!isCloudDeployment()) redirect("/");
  return <BookshelfHome publicOnly personalGuide />;
}
