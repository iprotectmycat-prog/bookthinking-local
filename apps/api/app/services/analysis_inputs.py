"""Versioned, immutable publication tickets. Contains no provider secrets."""

from dataclasses import dataclass, asdict, is_dataclass
from hashlib import sha256
import json


def _json_value(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if is_dataclass(value):
        return asdict(value)
    raise TypeError(f"Unsupported analysis input: {type(value).__name__}")


def fingerprint(value: object) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=_json_value).encode()).hexdigest()


def provider_configuration_signature(connection) -> str:
    # rowid order selects the active provider; sorting by name would miss a
    # switch back to a previously configured provider with unchanged values.
    provider = connection.execute("SELECT provider, model FROM provider_settings ORDER BY rowid").fetchall()
    from app.services.skill_analysis import selected_protocol, protocol_signature
    protocol = selected_protocol()
    return fingerprint({"providers": [tuple(row) for row in provider], "protocol": protocol,
                        "rules": protocol_signature() if protocol == "skill-v1" else None})


def configuration_signature(connection, book_id: str) -> str:
    genre = connection.execute("SELECT genre FROM books WHERE id=?", (book_id,)).fetchone()
    return fingerprint({"providers": provider_configuration_signature(connection), "genre": genre[0] if genre else None})


@dataclass(frozen=True)
class AnalysisInputSnapshot:
    book_id: str
    revision: int
    configuration: str
    input_fingerprint: str
    job_id: str | None = None
    result_versions: tuple[tuple[int, int], ...] | None = None


def ready_result_versions(connection, book_id: str) -> tuple[tuple[int, int], ...]:
    return tuple(tuple(row) for row in connection.execute(
        """SELECT a.chapter_id,a.content_version FROM chapter_analyses a
           JOIN chapters c ON c.id=a.chapter_id AND c.book_id=a.book_id
           WHERE a.book_id=? AND a.generation_status='ready' AND c.removed=0 ORDER BY a.chapter_id""",
        (book_id,),
    ))


def publication_allowed(connection, snapshot: AnalysisInputSnapshot, chapter_id: int | None = None, *, claim=False) -> bool:
    # Caller holds BEGIN IMMEDIATE until all content and evidence writes commit.
    revision = connection.execute(
        "SELECT analysis_input_revision FROM books WHERE id=?", (snapshot.book_id,)
    ).fetchone()
    valid = bool(revision and revision[0] == snapshot.revision)
    valid = valid and configuration_signature(connection, snapshot.book_id) == snapshot.configuration
    if snapshot.result_versions is not None:
        valid = valid and ready_result_versions(connection, snapshot.book_id) == snapshot.result_versions
    if snapshot.job_id:
        job = connection.execute(
            "SELECT status,input_revision,provider_signature FROM analysis_jobs WHERE id=? AND book_id=?",
            (snapshot.job_id, snapshot.book_id),
        ).fetchone()
        valid = valid and bool(job and job[0] == "running" and job[1] == snapshot.revision
                               and job[2] == provider_configuration_signature(connection))
    if chapter_id is not None:
        chapter = connection.execute(
            "SELECT 1 FROM chapters WHERE id=? AND book_id=? AND removed=0", (chapter_id, snapshot.book_id)
        ).fetchone()
        valid = valid and bool(chapter)
        if snapshot.job_id and not claim:
            active = connection.execute(
                "SELECT active_job_id FROM chapter_analyses WHERE book_id=? AND chapter_id=?",
                (snapshot.book_id, chapter_id),
            ).fetchone()
            valid = valid and bool(active and active[0] == snapshot.job_id)
    if not valid:
        if snapshot.job_id:
            connection.execute(
                """UPDATE analysis_jobs SET status='superseded',error_code='input_changed',
                   updated_at=CURRENT_TIMESTAMP WHERE id=? AND status IN ('queued','running')""",
                (snapshot.job_id,),
            )
        # Do not overwrite another task, a completed result, or a structure
        # repair's stale state when the old operation returns late.
        connection.execute(
            """UPDATE chapter_analyses SET generation_status='stale',failure_reason='分析输入已变化，请重新分析。'
               WHERE book_id=? AND generation_status='generating' AND active_job_id IS ?""",
            (snapshot.book_id, snapshot.job_id),
        )
    return valid
