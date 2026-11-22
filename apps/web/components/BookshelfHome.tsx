import Link from "next/link";

import styles from "../app/home.module.css";
import { AnalyzedBookShelf, PublicShelfNavigation } from "./AnalyzedBookShelf";

export function BookshelfHome({ publicOnly, personalGuide = false }: {
  publicOnly: boolean;
  personalGuide?: boolean;
}) {
  return (
    <main className={styles.page}>
      <nav className={styles.nav} aria-label="首页导航">
        <span className={styles.brand}>BookThinking</span>
        {!publicOnly && <div className={styles.utilities}><Link href="/settings">模型设置</Link></div>}
      </nav>
      <div className={styles.content}>
        <h1 className={styles.heading}>书架</h1>
        {personalGuide ? (
          <>
            <PublicShelfNavigation activeShelf="mine" />
            <section className={styles.empty} aria-labelledby="self-host-heading">
              <h2 id="self-host-heading">在自己的设备上导入书籍</h2>
              <p className={styles.guideDescription}>你可以自行部署 BookThinking，导入自己的书，并用自己的 API Key 生成阅读分析。</p>
              <a className={styles.importButton} href="https://github.com/iprotectmycat-prog/book-learning-system#本地开发">
                前往 GitHub 查看部署说明
              </a>
            </section>
          </>
        ) : <AnalyzedBookShelf showPublicShelf publicOnly={publicOnly} />}
      </div>
    </main>
  );
}
