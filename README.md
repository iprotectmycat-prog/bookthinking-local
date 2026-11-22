# BookThinking 本机版

BookThinking 是本机运行的书籍学习工具。导入文本层 PDF 或标准、无 DRM 的 EPUB 后，R12 先建立全书背景，再生成可回查原文的章节讲解。桌面和 iPad 共用阅读界面，本机 EPUB 还支持划线、备注和选中原文问 AI。

## 本地安装

安装 Python 3.12 或更新版本、uv、Node.js 24 和 pnpm 10 后，在仓库根目录安装依赖。

```bash
uv sync --project apps/api --locked
pnpm --dir apps/web install --frozen-lockfile
```

在两个终端中分别从仓库根目录启动 API 和 Web。

启动 API：

```bash
cd apps/api
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

启动 Web：

```bash
cd apps/web
pnpm dev --hostname 127.0.0.1
```

桌面浏览器访问 <http://127.0.0.1:3000/>，打开「模型设置」填写自己的 API Key，再回书架导入书籍。建议把单用户服务绑定在回环地址。首页书架支持桌面与手机布局，默认显示一排，向下滑动可展开更多书籍；页面配色自动跟随系统深浅设置。

## 使用

1. 在「模型设置」中选择 OpenAI 或 DeepSeek，填写模型名称和自己的 API Key。
2. 从书架点击「导入书籍」，选择标准且无 DRM 的 EPUB，核对并确认章节。
3. 分析完成后，从书籍总览进入章节讲解，点击引用回查原文。

原书、章节和分析结果默认保存在本机 `~/.book-learning`。在 macOS 上，模型密钥保存在系统钥匙串，分析时会把所需的原文提交给所选模型服务。图片和扫描页不会经过 OCR。

脚本也可以通过本机 Web 的 `/local` 接口上传 EPUB。按顺序调用 `POST /local/books`（multipart 字段 `file`）、`PUT /local/books/{id}/chapters`（确认章节）、`POST /local/books/{id}/analyses`（启动分析），再查询 `GET /local/books/{id}/analysis-jobs/{job_id}`。上传接口返回书籍 ID 和待确认的章节。

## 运行测试

```bash
(cd apps/api && .venv/bin/python -m pytest)
(cd apps/web && pnpm test && pnpm lint && pnpm build)
```
