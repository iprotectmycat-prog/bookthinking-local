import json

import httpx
import pytest

from app.api.routes.analyses import get_analysis_provider
from app.main import create_app
from app.runtime import RuntimeSettings
from app.services.accounts import AccountRepository
from app.services.analysis_providers import OpenAICompatibleAnalysisProvider
from app.services.storage import ApplicationPaths, BookRepository


@pytest.mark.anyio
async def test_source_chat_sends_excerpt_and_follow_up_to_configured_model(tmp_path, monkeypatch):
    monkeypatch.setenv("BOOK_LEARNING_HOME", str(tmp_path))
    paths = ApplicationPaths.from_environment()
    paths.ensure_exists()
    owner = AccountRepository(paths.database_path).get_or_bootstrap_local_owner()
    BookRepository(paths.database_path).save_book_import(
        book_id="sample", owner_id=owner.id, filename="sample.epub",
        sha256="sample", stored_path=tmp_path / "sample.epub", status="parsed",
        source_format="epub", diagnostics=[], pages=[], chapters=[],
    )
    requests = []

    def reply(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {
            "content": "这一点是推断。", "reasoning_content": "先检查上下文。",
        }}]})

    app = create_app(RuntimeSettings(deployment_mode="local", secret_backend="environment", analysis_workers=1))
    with httpx.Client(transport=httpx.MockTransport(reply)) as model_client:
        app.dependency_overrides[get_analysis_provider] = lambda: OpenAICompatibleAnalysisProvider(
            base_url="https://api.deepseek.com", api_key="test", model="deepseek-v4-flash", client=model_client,
        )
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            settings = await client.get("/books/sample/source-chat")
            response = await client.post("/books/sample/source-chat", json={
                "quote": "原书片段",
                "before": "前文",
                "after": "后文",
                "chapter_summary": "章节提要",
                "turns": [{"question": "作者想说什么？", "answer": "这是作者给出的例子。"}],
                "question": "这也是作者的结论吗？",
                "thinking": "high",
            })

    assert response.status_code == 200
    assert settings.json() == {"model": "deepseek-v4-flash", "thinking_options": ["off", "low", "high"]}
    assert response.json() == {"answer": "这一点是推断。", "model": "deepseek-v4-flash", "thinking": "先检查上下文。"}
    assert requests[0]["thinking"] == {"type": "enabled"}
    assert requests[0]["reasoning_effort"] == "high"
    assert "response_format" not in requests[0]
    messages = requests[0]["messages"]
    assert all(text in messages[1]["content"] for text in ("原书片段", "前文", "后文", "章节提要"))
    assert messages[-3:] == [
        {"role": "user", "content": "作者想说什么？"},
        {"role": "assistant", "content": "这是作者给出的例子。"},
        {"role": "user", "content": "这也是作者的结论吗？"},
    ]
