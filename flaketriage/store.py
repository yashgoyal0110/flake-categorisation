"""SQLite persistence.

The store exists before the classifier for a reason. Podman keeps no record of which failures were
flakes, so there is nothing to measure an agent against. Collecting that record is useful on its
own, even if the model half turned out to be worthless.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .models import Category, Flake, Verdict

SCHEMA = """
CREATE TABLE IF NOT EXISTS flake (
    job_id       INTEGER PRIMARY KEY,
    run_id       INTEGER NOT NULL,
    run_attempt  INTEGER NOT NULL,
    job_name     TEXT    NOT NULL,
    head_sha     TEXT    NOT NULL,
    html_url     TEXT    NOT NULL,
    detected_by  TEXT    NOT NULL,
    failed_at    TEXT    NOT NULL,
    excerpt      TEXT    NOT NULL DEFAULT '',
    category     TEXT,
    confidence   REAL,
    summary      TEXT,
    suggestion   TEXT,
    classifier   TEXT,
    evidence     TEXT
);

-- The report groups by category and orders by recency, and the dashboard filters by job name.
CREATE INDEX IF NOT EXISTS idx_flake_failed_at ON flake (failed_at DESC);
CREATE INDEX IF NOT EXISTS idx_flake_category  ON flake (category);
CREATE INDEX IF NOT EXISTS idx_flake_job_name  ON flake (job_name);
"""


class Store:
    def __init__(self, path: str | Path = "flakes.db") -> None:
        self.path = str(path)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def save(self, flake: Flake) -> None:
        """Insert or update by job id.

        Upsert rather than insert, because ingestion is expected to be re-run over an overlapping
        window and a job id identifies exactly one attempt of one job forever.
        """
        v = flake.verdict
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO flake (job_id, run_id, run_attempt, job_name, head_sha, html_url,
                                   detected_by, failed_at, excerpt, category, confidence,
                                   summary, suggestion, classifier, evidence)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(job_id) DO UPDATE SET
                    excerpt=excluded.excerpt, category=excluded.category,
                    confidence=excluded.confidence, summary=excluded.summary,
                    suggestion=excluded.suggestion, classifier=excluded.classifier,
                    evidence=excluded.evidence
                """,
                (
                    flake.job_id, flake.run_id, flake.run_attempt, flake.job_name,
                    flake.head_sha, flake.html_url, flake.detected_by, flake.failed_at,
                    flake.excerpt,
                    v.category.value if v else None,
                    v.confidence if v else None,
                    v.summary if v else None,
                    v.suggestion if v else None,
                    v.classifier if v else None,
                    json.dumps(v.evidence) if v else None,
                ),
            )

    def unclassified(self, limit: int = 100) -> list[Flake]:
        return self._query("SELECT * FROM flake WHERE category IS NULL "
                           "ORDER BY failed_at DESC LIMIT ?", (limit,))

    def all(self, limit: int = 500) -> list[Flake]:
        return self._query("SELECT * FROM flake ORDER BY failed_at DESC LIMIT ?", (limit,))

    def since(self, iso_timestamp: str) -> list[Flake]:
        return self._query("SELECT * FROM flake WHERE failed_at >= ? ORDER BY failed_at DESC",
                           (iso_timestamp,))

    def count_by_category(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT COALESCE(category, 'unclassified') AS c, COUNT(*) AS n "
                "FROM flake GROUP BY c ORDER BY n DESC"
            ).fetchall()
        return {r["c"]: r["n"] for r in rows}

    def _query(self, sql: str, args: tuple) -> list[Flake]:
        with self._connect() as conn:
            rows = conn.execute(sql, args).fetchall()
        return [_row_to_flake(r) for r in rows]


def _row_to_flake(row: sqlite3.Row) -> Flake:
    verdict = None
    if row["category"]:
        verdict = Verdict(
            category=Category(row["category"]),
            confidence=row["confidence"] or 0.0,
            summary=row["summary"] or "",
            suggestion=row["suggestion"] or "",
            classifier=row["classifier"] or "",
            evidence=json.loads(row["evidence"]) if row["evidence"] else [],
        )
    return Flake(
        job_id=row["job_id"], run_id=row["run_id"], run_attempt=row["run_attempt"],
        job_name=row["job_name"], head_sha=row["head_sha"], html_url=row["html_url"],
        detected_by=row["detected_by"], failed_at=row["failed_at"],
        excerpt=row["excerpt"], verdict=verdict,
    )
