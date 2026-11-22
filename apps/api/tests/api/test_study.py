from io import BytesIO

import httpx
import pytest
from reportlab.pdfgen.canvas import Canvas

from app.main import app


def make_source_pdf() -> bytes:
    output = BytesIO()
    canvas = Canvas(output)
    canvas.drawString(72, 720, "Capital costs affect the present value of future cash flows.")
    canvas.showPage()
    canvas.save()
    return output.getvalue()


@pytest.mark.anyio
async def test_generates_evidence_backed_unit_without_revealing_answer(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BOOK_LEARNING_HOME", str(tmp_path))
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        imported = await client.post(
            "/books",
            files={"file": ("sample.pdf", make_source_pdf(), "application/pdf")},
        )
        book_id = imported.json()["id"]
        await client.put(
            f"/books/{book_id}/chapters",
            json={"chapters": [{"title": "资本成本", "source_start_page": 1, "source_end_page": 1}]},
        )
        response = await client.post(f"/books/{book_id}/learning-units")
        answered = await client.post(
            f"/learning-units/{response.json()['id']}/predictions", json={"answer": "A"}
        )

    assert response.status_code == 201
    body = response.json()
    assert body["prediction"]["correct_answer"] is None
    assert body["evidence"] == [
        {"chapter": "资本成本", "page": 1, "quote": "Capital costs affect the present value of future cash flows."}
    ]
    assert answered.status_code == 200
    assert answered.json()["prediction"] == {"selected_answer": "A", "correct_answer": "A", "is_correct": True}
    assert answered.json()["explanation"] == "选项 A 可以在本章原文中直接定位，其余选项没有对应的原文证据。"
