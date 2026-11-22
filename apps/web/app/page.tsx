import { BookshelfHome } from "../components/BookshelfHome";
import { isCloudDeployment } from "../lib/deployment-mode";

export default function HomePage() {
  return <BookshelfHome publicOnly={isCloudDeployment()} />;
}
