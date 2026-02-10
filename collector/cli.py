from __future__ import annotations

import argparse
import os
from datetime import datetime
from typing import Any

from .db import SqliteStore
from .firestore import FirestoreWriter, firestore_enabled
from .http import HttpClient, HttpConfig, DEFAULT_UA
from .schema import iso_now_kst
from .sitegen import (
    export_md_all_items,
    export_md_items,
    prepare_weekly,
    write_index_portal,
    write_source_indexes,
    write_weekly_pages,
)
from .sources import SOURCES


def default_db_path() -> str:
    return os.path.join(os.getcwd(), ".collector", "collector.sqlite")


def cmd_run(args: argparse.Namespace) -> int:
    http = HttpClient(HttpConfig(user_agent=(args.user_agent or DEFAULT_UA)))
    store = SqliteStore(args.db)
    fw = FirestoreWriter(collection=args.firestore_collection) if firestore_enabled() else None

    selected = [s.strip() for s in args.sources]
    for s in selected:
        if s not in SOURCES:
            raise SystemExit(f"Unknown source: {s}. Valid: {', '.join(SOURCES)}")

    total_new = 0
    for src_name in selected:
        src = SOURCES[src_name](http)
        for li in src.iter_list(since_days=args.since_days, max_pages=args.max_pages):
            site_id = li["site_id"]
            if store.has_site_id(src_name, site_id):
                continue
            # Fetch detail
            content_text = ""
            attachments = li.get("attachments") or []
            tags = li.get("tags") or []
            raw_html = None
            try:
                ct, at, tg, rh = src.fetch_detail(site_id, li["url"])
                content_text = ct or ""
                # merge attachment lists
                attachments = attachments + (at or [])
                tags = list(dict.fromkeys((tags or []) + (tg or [])))
                raw_html = rh if args.save_raw_html else None
            except Exception as e:
                # For MVP: store list-only if detail fails
                if args.verbose:
                    print(f"[{src_name}] detail fetch failed for {site_id}: {e}")

            item: dict[str, Any] = {
                "id": li["id"],
                "source": li["source"],
                "org": li["org"],
                "site_id": site_id,
                "title": li["title"],
                "published_at": li.get("published_at"),
                "url": li["url"],
                "content_text": content_text,
                "tags": tags,
                "attachments": _dedupe_attachments(attachments),
                "fetched_at": iso_now_kst(),
            }
            if raw_html is not None:
                item["raw_html"] = raw_html

            store.upsert_item(item)
            total_new += 1
            if fw:
                try:
                    fw.upsert(item)
                except Exception as e:
                    if args.verbose:
                        print(f"[firestore] upsert failed for {item['id']}: {e}")

            if args.verbose:
                print(f"[{src_name}] + {site_id} {item['published_at']} {item['title']}")

    print(f"Done. new_items={total_new} db={args.db} firestore={'on' if fw else 'off'}")
    return 0


def _dedupe_attachments(atts: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for a in atts or []:
        url = (a or {}).get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(a)
    return out


def _iter_items_any(args: argparse.Namespace):
    """Prefer SQLite; fallback to JSONL if requested or DB missing."""
    db_path = getattr(args, "db", None)
    jsonl_path = getattr(args, "jsonl", None)

    if db_path and os.path.exists(db_path):
        store = SqliteStore(db_path)
        yield from store.iter_items(sources=list(args.sources) if getattr(args, "sources", None) else None)
        return

    if jsonl_path and os.path.exists(jsonl_path):
        import json

        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                yield json.loads(line)
        return

    raise SystemExit(
        f"No data source found. SQLite missing at {db_path!r}. "
        + (f"JSONL missing at {jsonl_path!r}." if jsonl_path else "Provide --jsonl to use JSONL.")
    )


def cmd_export_jsonl(args: argparse.Namespace) -> int:
    store = SqliteStore(args.db)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        for item in store.iter_items(sources=list(args.sources) if args.sources else None):
            import json

            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(f"Wrote {args.out}")
    return 0


def cmd_export_md(args: argparse.Namespace) -> int:
    stats = export_md_items(
        _iter_items_any(args),
        outdir=args.outdir,
        days=args.days,
    )
    print(f"export-md: outdir={args.outdir} days={args.days} written={stats['written']} cutoff={stats['cutoff']}")
    return 0


def cmd_build_weekly(args: argparse.Namespace) -> int:
    w = prepare_weekly(_iter_items_any(args), days=args.days)
    paths = write_weekly_pages(w, outdir=args.outdir)
    print(
        "build-weekly: "
        + f"outdir={args.outdir} days={args.days} items={len(w.items)} "
        + f"weekly_latest={paths['latest']} weekly_dated={paths['dated']}"
    )
    return 0


def cmd_build_site(args: argparse.Namespace) -> int:
    # Single data loading pass
    items = list(_iter_items_any(args))

    # Ensure item pages exist for all items referenced by portal/source pages
    item_stats = export_md_all_items(items, outdir=args.outdir)

    # Portal index + per-source archive pages
    idx = write_index_portal(items, outdir=args.outdir, days=args.days, limit=args.limit)
    src_paths = write_source_indexes(items, outdir=args.outdir)

    print(
        "build-site: "
        + f"outdir={args.outdir} items={len(items)} item_pages_written={item_stats['written']} "
        + f"index={idx} sources={len(src_paths)}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="collector", description="Weekly incremental press-release collector (MVP).")
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("run", help="Fetch new items and store incrementally.")
    pr.add_argument("--sources", nargs="+", default=["rda", "nics", "nihhs"], help="Sources to run")
    pr.add_argument("--since-days", type=int, default=30, help="Only collect items within this many days")
    pr.add_argument("--max-pages", type=int, default=3, help="Max pages to scan per source (where supported)")
    pr.add_argument("--db", default=default_db_path(), help="SQLite path")
    pr.add_argument("--user-agent", default=None, help="Override User-Agent")
    pr.add_argument("--save-raw-html", action="store_true", help="Store raw HTML in SQLite")
    pr.add_argument("--firestore-collection", default="press_items", help="Firestore collection name")
    pr.add_argument("--verbose", action="store_true")
    pr.set_defaults(func=cmd_run)

    pe = sub.add_parser("export-jsonl", help="Export items from SQLite to JSONL")
    pe.add_argument("--db", default=default_db_path(), help="SQLite path")
    pe.add_argument("--out", default=os.path.join(os.getcwd(), ".collector", "export.jsonl"), help="Output JSONL path")
    pe.add_argument("--sources", nargs="*", default=None, help="Filter by sources")
    pe.set_defaults(func=cmd_export_jsonl)

    pm = sub.add_parser("export-md", help="Export recent items as GitHub-Pages-friendly Markdown")
    pm.add_argument("--outdir", default=os.path.join(os.getcwd(), "site"), help="Output directory (tracked)")
    pm.add_argument("--days", type=int, default=7, help="Only export items within last N days")
    pm.add_argument("--db", default=default_db_path(), help="SQLite path (preferred)")
    pm.add_argument(
        "--jsonl",
        default=os.path.join(os.getcwd(), ".collector", "export.jsonl"),
        help="Fallback JSONL path (used if SQLite missing)",
    )
    pm.add_argument("--sources", nargs="*", default=None, help="Filter by sources")
    pm.set_defaults(func=cmd_export_md)

    pw = sub.add_parser("build-weekly", help="Build a weekly Markdown digest page (last N days)")
    pw.add_argument("--outdir", default=os.path.join(os.getcwd(), "site"), help="Output directory (tracked)")
    pw.add_argument("--days", type=int, default=7, help="Include items within last N days")
    pw.add_argument("--db", default=default_db_path(), help="SQLite path (preferred)")
    pw.add_argument(
        "--jsonl",
        default=os.path.join(os.getcwd(), ".collector", "export.jsonl"),
        help="Fallback JSONL path (used if SQLite missing)",
    )
    pw.add_argument("--sources", nargs="*", default=None, help="Filter by sources")
    pw.set_defaults(func=cmd_build_weekly)

    ps = sub.add_parser("build-site", help="Build portal index + per-source archive pages")
    ps.add_argument("--outdir", default=os.path.join(os.getcwd(), "site"), help="Output directory (tracked)")
    ps.add_argument("--days", type=int, default=7, help="Recent window in days (used on portal index)")
    ps.add_argument("--limit", type=int, default=25, help="Max items to show in Recent section")
    ps.add_argument("--db", default=default_db_path(), help="SQLite path (preferred)")
    ps.add_argument(
        "--jsonl",
        default=os.path.join(os.getcwd(), ".collector", "export.jsonl"),
        help="Fallback JSONL path (used if SQLite missing)",
    )
    ps.add_argument("--sources", nargs="*", default=None, help="Filter by sources")
    ps.set_defaults(func=cmd_build_site)

    args = p.parse_args(argv)

    # User-Agent handling: NIHHS requires UA; provide default if not set
    if getattr(args, "user_agent", None) is None:
        # Use default UA in HttpConfig
        args.user_agent = None

    return args.func(args)
