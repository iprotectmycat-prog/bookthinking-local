"""Durable admission and lifecycle for the single-process analysis runner."""

import json
from pathlib import Path
from uuid import uuid4

from app.services.storage import open_connection
from app.services.analysis_inputs import provider_configuration_signature


ACTIVE_JOB_STATUSES = {"queued", "running"}


class AnalysisJobConflict(ValueError):
    pass


def initialize_analysis_schema(connection) -> None:
    connection.execute("""
        CREATE TABLE IF NOT EXISTS analysis_jobs (
            id TEXT PRIMARY KEY, book_id TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
            kind TEXT NOT NULL, target_chapter_ids_json TEXT NOT NULL, request_key TEXT NOT NULL,
            status TEXT NOT NULL, stage TEXT NOT NULL DEFAULT 'chapters',
            input_revision INTEGER NOT NULL,
            completed_chapter_ids_json TEXT NOT NULL DEFAULT '[]',
            failed_chapter_ids_json TEXT NOT NULL DEFAULT '[]', error_code TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    columns = {row[1] for row in connection.execute("PRAGMA table_info(analysis_jobs)")}
    if "provider_signature" not in columns:
        connection.execute("ALTER TABLE analysis_jobs ADD COLUMN provider_signature TEXT NOT NULL DEFAULT ''")
    connection.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS analysis_jobs_one_active_book
        ON analysis_jobs(book_id) WHERE status IN ('queued', 'running')
    """)
    # Triggers also cover scripts and transactional structure repair. Only actual
    # changes to model inputs advance the revision; analysis writes never do.
    for table, columns in {
        "chapters": ["position", "title", "source_start_page", "source_end_page", "depth",
                     "parent_title", "nav_kind", "in_body", "structural_role", "analysis_role",
                     "source_locator", "removed"],
        "book_pages": ["text", "page_number"],
    }.items():
        condition = " OR ".join(f"OLD.{column} IS NOT NEW.{column}" for column in columns)
        for event in ("INSERT", "UPDATE", "DELETE"):
            row = "OLD" if event == "DELETE" else "NEW"
            when = f"WHEN {condition}" if event == "UPDATE" else ""
            connection.execute(f"""
                CREATE TRIGGER IF NOT EXISTS analysis_revision_{table}_{event.lower()}
                AFTER {event} ON {table} {when}
                BEGIN
                    UPDATE books SET analysis_input_revision = analysis_input_revision + 1
                    WHERE id = {row}.book_id;
                END
            """)
    columns = ("title", "subtitle", "authors", "publisher")
    condition = " OR ".join(f"OLD.{column} IS NOT NEW.{column}" for column in columns)
    connection.execute(f"""
        CREATE TRIGGER IF NOT EXISTS analysis_revision_metadata
        AFTER UPDATE OF {", ".join(columns)} ON books WHEN {condition}
        BEGIN
            UPDATE books SET analysis_input_revision = analysis_input_revision + 1 WHERE id = NEW.id;
        END
    """)


def _job(row) -> dict | None:
    if row is None:
        return None
    result = dict(zip(
        ("id", "book_id", "kind", "target_chapter_ids_json", "request_key", "status",
         "stage", "input_revision", "completed_chapter_ids_json", "failed_chapter_ids_json",
         "error_code", "created_at", "updated_at"), row
    ))
    for name in ("target_chapter_ids", "completed_chapter_ids", "failed_chapter_ids"):
        result[name] = json.loads(result.pop(name + "_json"))
    return result


class AnalysisJobStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def admit(self, book_id: str, kind: str, chapter_ids: list[int], request_key: str, *, provider_identity=None) -> tuple[dict, bool]:
        with open_connection(self.database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            if provider_identity is not None:
                current = connection.execute(
                    "SELECT provider,model FROM provider_settings ORDER BY rowid DESC LIMIT 1"
                ).fetchone()
                if not current or dict(zip(("provider", "model"), current)) != provider_identity:
                    raise AnalysisJobConflict("模型配置已变化，请重新提交分析。")
            revision = connection.execute(
                "SELECT analysis_input_revision FROM books WHERE id = ?", (book_id,)
            ).fetchone()[0]
            key = f"{revision}:{request_key}"
            active = _job(connection.execute(
                "SELECT * FROM analysis_jobs WHERE book_id=? AND status IN ('queued','running')",
                (book_id,),
            ).fetchone())
            if active:
                if active["request_key"] == key:
                    return active, False
                raise AnalysisJobConflict("本书已有分析任务，请等待完成后重试。")
            job_id = str(uuid4())
            connection.execute(
                """INSERT INTO analysis_jobs(id,book_id,kind,target_chapter_ids_json,request_key,status,input_revision,provider_signature)
                   VALUES (?,?,?,?,?,'queued',?,?)""",
                (job_id, book_id, kind, json.dumps(chapter_ids), key, revision, provider_configuration_signature(connection)),
            )
            return _job(connection.execute("SELECT * FROM analysis_jobs WHERE id=?", (job_id,)).fetchone()), True

    def get(self, book_id: str, job_id: str) -> dict | None:
        with open_connection(self.database_path) as connection:
            return _job(connection.execute(
                "SELECT * FROM analysis_jobs WHERE book_id=? AND id=?", (book_id, job_id)
            ).fetchone())

    def latest(self, book_id: str) -> dict | None:
        with open_connection(self.database_path) as connection:
            return _job(connection.execute(
                "SELECT * FROM analysis_jobs WHERE book_id=? ORDER BY rowid DESC LIMIT 1", (book_id,)
            ).fetchone())

    def start(self, job: dict) -> bool:
        with open_connection(self.database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            revision = connection.execute(
                "SELECT analysis_input_revision FROM books WHERE id=?", (job["book_id"],)
            ).fetchone()
            provider = connection.execute("SELECT provider_signature FROM analysis_jobs WHERE id=?", (job["id"],)).fetchone()
            current = bool(revision and revision[0] == job["input_revision"]
                           and provider and provider[0] == provider_configuration_signature(connection))
            status = "running" if current else "superseded"
            changed = connection.execute(
                "UPDATE analysis_jobs SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='queued'",
                (status, job["id"]),
            ).rowcount
            return changed == 1 and status == "running"

    def stage(self, job_id: str, stage: str) -> None:
        with open_connection(self.database_path) as connection:
            connection.execute("UPDATE analysis_jobs SET stage=? WHERE id=? AND status='running'", (stage, job_id))

    def finish(self, job_id: str, status: str, *, completed=(), failed=(), error_code=None) -> None:
        with open_connection(self.database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            revisions = connection.execute(
                """SELECT j.input_revision,b.analysis_input_revision,j.provider_signature FROM analysis_jobs j
                   JOIN books b ON b.id=j.book_id WHERE j.id=?""", (job_id,)
            ).fetchone()
            if revisions and (revisions[0] != revisions[1] or revisions[2] != provider_configuration_signature(connection)):
                status, error_code = "superseded", "input_changed"
            connection.execute(
                """UPDATE analysis_jobs SET status=?,completed_chapter_ids_json=?,failed_chapter_ids_json=?,
                   error_code=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND status IN ('queued','running')""",
                (status, json.dumps(list(completed)), json.dumps(list(failed)), error_code, job_id),
            )

    def recover_interrupted(self) -> None:
        with open_connection(self.database_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """UPDATE analysis_jobs SET status='interrupted',error_code='analysis_interrupted',
                   updated_at=CURRENT_TIMESTAMP WHERE status IN ('queued','running')"""
            )
            connection.execute(
                """UPDATE chapter_analyses SET generation_status='failed',failure_reason='分析已中断，请重新分析。'
                   WHERE generation_status='generating' AND (
                     active_job_id IS NULL OR active_job_id IN (
                       SELECT id FROM analysis_jobs WHERE status='interrupted'))"""
            )
