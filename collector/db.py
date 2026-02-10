from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from typing import Any, Iterable, Optional


SCHEMA_SQL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS items (
  id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  org TEXT NOT NULL,
  site_id TEXT NOT NULL,
  title TEXT NOT NULL,
  published_at TEXT,
  url TEXT NOT NULL,
  content_text TEXT,
  tags_json TEXT,
  attachments_json TEXT,
  fetched_at TEXT,
  raw_html TEXT,
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now')),
  UNIQUE(source, site_id)
);

CREATE INDEX IF NOT EXISTS idx_items_source_published ON items(source, published_at);
"""


class SqliteStore:
    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con

    def _init(self):
        with self._connect() as con:
            con.executescript(SCHEMA_SQL)

    @contextmanager
    def conn(self):
        con = self._connect()
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def has_site_id(self, source: str, site_id: str) -> bool:
        with self.conn() as con:
            row = con.execute(
                "SELECT 1 FROM items WHERE source=? AND site_id=? LIMIT 1", (source, site_id)
            ).fetchone()
            return row is not None

    def upsert_item(self, item: dict[str, Any]):
        # Serialize list fields
        tags_json = json.dumps(item.get("tags") or [], ensure_ascii=False)
        attachments_json = json.dumps(item.get("attachments") or [], ensure_ascii=False)
        with self.conn() as con:
            con.execute(
                """
                INSERT INTO items(
                  id, source, org, site_id, title, published_at, url, content_text,
                  tags_json, attachments_json, fetched_at, raw_html, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?, datetime('now'))
                ON CONFLICT(id) DO UPDATE SET
                  source=excluded.source,
                  org=excluded.org,
                  site_id=excluded.site_id,
                  title=excluded.title,
                  published_at=excluded.published_at,
                  url=excluded.url,
                  content_text=excluded.content_text,
                  tags_json=excluded.tags_json,
                  attachments_json=excluded.attachments_json,
                  fetched_at=excluded.fetched_at,
                  raw_html=excluded.raw_html,
                  updated_at=datetime('now')
                """,
                (
                    item.get("id"),
                    item.get("source"),
                    item.get("org"),
                    item.get("site_id"),
                    item.get("title"),
                    item.get("published_at"),
                    item.get("url"),
                    item.get("content_text"),
                    tags_json,
                    attachments_json,
                    item.get("fetched_at"),
                    item.get("raw_html"),
                ),
            )

    def iter_items(self, *, sources: Optional[list[str]] = None) -> Iterable[dict[str, Any]]:
        with self.conn() as con:
            if sources:
                q = "SELECT * FROM items WHERE source IN (%s) ORDER BY published_at DESC" % (
                    ",".join("?" for _ in sources)
                )
                rows = con.execute(q, sources).fetchall()
            else:
                rows = con.execute("SELECT * FROM items ORDER BY published_at DESC").fetchall()

        for r in rows:
            d = dict(r)
            d["tags"] = json.loads(d.pop("tags_json") or "[]")
            d["attachments"] = json.loads(d.pop("attachments_json") or "[]")
            return_raw = d.get("raw_html")
            if return_raw is None:
                d.pop("raw_html", None)
            yield d
