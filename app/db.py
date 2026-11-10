from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS custom_scans (
    scan_id TEXT PRIMARY KEY,
    display_id TEXT NOT NULL UNIQUE,
    pixel_sha256 TEXT NOT NULL UNIQUE,
    canonical_path TEXT NOT NULL,
    manifest_path TEXT NOT NULL,
    original_path TEXT,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    axial_um REAL,
    lateral_um REAL,
    spacing_provenance TEXT,
    origin_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_utc TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS custom_results (
    scan_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    result_path TEXT NOT NULL,
    result_sha256 TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    created_utc TEXT NOT NULL,
    PRIMARY KEY (scan_id, model_id),
    FOREIGN KEY (scan_id) REFERENCES custom_scans(scan_id)
);
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    scan_id TEXT NOT NULL,
    state TEXT NOT NULL,
    job_path TEXT NOT NULL,
    created_utc TEXT NOT NULL,
    updated_utc TEXT NOT NULL
);
"""


class CatalogueDB:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def find_custom_by_hash(self, digest: str) -> dict | None:
        with self.connect() as con:
            row = con.execute(
                "SELECT * FROM custom_scans WHERE pixel_sha256=? AND status='active'", (digest,)
            ).fetchone()
        return dict(row) if row else None

    def get_custom(self, scan_id: str, include_trashed: bool = False) -> dict | None:
        sql = "SELECT * FROM custom_scans WHERE scan_id=?"
        args: tuple = (scan_id,)
        if not include_trashed:
            sql += " AND status='active'"
        with self.connect() as con:
            row = con.execute(sql, args).fetchone()
        return dict(row) if row else None

    def list_custom(self) -> list[dict]:
        with self.connect() as con:
            rows = con.execute(
                "SELECT * FROM custom_scans WHERE status='active' ORDER BY created_utc DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def insert_custom(self, record: dict) -> None:
        keys = (
            "scan_id", "display_id", "pixel_sha256", "canonical_path", "manifest_path",
            "original_path", "width", "height", "axial_um", "lateral_um",
            "spacing_provenance", "origin_json", "status", "created_utc",
        )
        with self.connect() as con:
            con.execute(
                f"INSERT INTO custom_scans ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})",
                tuple(record.get(key) for key in keys),
            )

    def set_custom_status(self, scan_id: str, status: str) -> None:
        with self.connect() as con:
            con.execute("UPDATE custom_scans SET status=? WHERE scan_id=?", (status, scan_id))

    def upsert_result(self, record: dict) -> None:
        with self.connect() as con:
            con.execute(
                """INSERT INTO custom_results
                   (scan_id,model_id,result_path,result_sha256,provenance_json,created_utc)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(scan_id,model_id) DO UPDATE SET
                     result_path=excluded.result_path,
                     result_sha256=excluded.result_sha256,
                     provenance_json=excluded.provenance_json,
                     created_utc=excluded.created_utc""",
                (
                    record["scan_id"], record["model_id"], record["result_path"],
                    record["result_sha256"], json.dumps(record["provenance"], sort_keys=True),
                    record["created_utc"],
                ),
            )

    def list_results(self, scan_id: str) -> list[dict]:
        with self.connect() as con:
            rows = con.execute(
                "SELECT * FROM custom_results WHERE scan_id=? ORDER BY model_id", (scan_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def insert_job(self, record: dict) -> None:
        with self.connect() as con:
            con.execute(
                "INSERT INTO jobs (job_id,scan_id,state,job_path,created_utc,updated_utc) VALUES (?,?,?,?,?,?)",
                (record["job_id"], record["scan_id"], record["state"], record["job_path"], record["created_utc"], record["updated_utc"]),
            )

    def get_job(self, job_id: str) -> dict | None:
        with self.connect() as con:
            row = con.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        return dict(row) if row else None

