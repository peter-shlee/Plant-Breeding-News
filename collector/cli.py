from __future__ import annotations

import argparse
import os
from datetime import datetime
from typing import Any

from .db import SqliteStore
from .enrich import attachment_key, auto_tags, generate_summary, is_view_link
from .filtering import decide_plant_only, decide_breeding_relevance
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

    # Repo-state dedupe (CI-friendly): treat already-exported docs/items as "known".
    exported = _load_exported_site_ids_from_repo(os.getcwd())

    selected = [s.strip() for s in args.sources]
    for s in selected:
        if s not in SOURCES:
            raise SystemExit(f"Unknown source: {s}. Valid: {', '.join(SOURCES)}")

    total_new = 0
    total_skipped_filter = 0
    total_skipped_repo = 0

    for src_name in selected:
        src = SOURCES[src_name](http)
        for li in src.iter_list(since_days=args.since_days, max_pages=args.max_pages):
            site_id = li["site_id"]

            if store.has_site_id(src_name, site_id):
                continue

            # Default plant-only filtering (conservative): skip obvious animal/pet/livestock posts.
            # Do this BEFORE detail fetch to reduce load.
            pre_decision = decide_plant_only(title=li.get("title") or "", content_text="", tags=li.get("tags") or [])
            if not pre_decision.keep:
                total_skipped_filter += 1
                if args.verbose:
                    print(
                        f"[{src_name}] - (filter:{pre_decision.reason}) {site_id} {li.get('published_at')} {li.get('title')}"
                    )
                continue

            # Repo-state dedupe (CI): if item page already exists in docs/, skip detail fetch.
            repo_key = f"{src_name}:{site_id}"
            repo_known = repo_key in exported
            if repo_known:
                total_skipped_repo += 1

            # Some sources (e.g., RSS) already provide list-level content_text (summary).
            content_text = li.get("content_text") or ""
            attachments = li.get("attachments") or []
            tags = li.get("tags") or []
            raw_html = None

            # If the list stage already provides content_text, we can skip detail fetch.
            need_detail = (not content_text.strip())

            if not repo_known and need_detail:
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

            # Optional: additional relevance filter for noisy feeds (ScienceDaily).
            if src_name == "sciencedaily":
                rel_decision = decide_breeding_relevance(
                    title=li.get("title") or "",
                    content_text=content_text,
                    tags=tags,
                    min_score=2.0,
                )
                if not rel_decision.keep:
                    total_skipped_filter += 1
                    if args.verbose:
                        print(
                            f"[{src_name}] - (filter:{rel_decision.reason}) {site_id} {li.get('published_at')} {li.get('title')}"
                        )
                    continue

            # Post-filter with detail text (keeps mixed/plant mentions).
            post_decision = decide_plant_only(title=li.get("title") or "", content_text=content_text, tags=tags)
            if not post_decision.keep:
                total_skipped_filter += 1
                if args.verbose:
                    print(
                        f"[{src_name}] - (filter:{post_decision.reason}) {site_id} {li.get('published_at')} {li.get('title')}"
                    )
                continue

            tags = auto_tags(title=li.get("title") or "", content_text=content_text, existing=tags)
            summary = generate_summary(content_text)
            attachments = _dedupe_attachments(attachments)

            item: dict[str, Any] = {
                "id": li["id"],
                "source": li["source"],
                "org": li["org"],
                "site_id": site_id,
                "title": li["title"],
                "published_at": li.get("published_at"),
                "url": li["url"],
                "content_text": content_text,
                "summary": summary,
                "tags": tags,
                "attachments": attachments,
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
                extra = " (repo-known)" if repo_known else ""
                print(f"[{src_name}] + {site_id}{extra} {item['published_at']} {item['title']}")

    print(
        "Done. "
        + f"new_items={total_new} skipped_filter={total_skipped_filter} skipped_repo_known={total_skipped_repo} "
        + f"db={args.db} firestore={'on' if fw else 'off'}"
    )
    return 0


def _dedupe_attachments(atts: list[dict]) -> list[dict]:
    """De-dupe attachments.

    Heuristics:
    - Prefer download links over view/preview links when both exist.
    - If same document is available in multiple formats, prefer: pdf > hwpx > hwp.
    """

    priority = {"pdf": 3, "hwpx": 2, "hwp": 1, "": 0}

    # First pass: de-dupe by URL, keep order.
    seen_urls: set[str] = set()
    cleaned: list[dict] = []
    for a in atts or []:
        url = (a or {}).get("url")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        cleaned.append(a)

    # Second pass: group by (base, ext) and prefer non-view links.
    by_key: dict[tuple[str, str], dict] = {}
    for a in cleaned:
        url = (a or {}).get("url") or ""
        title = (a or {}).get("title")
        key = attachment_key(url, title=title)

        prev = by_key.get(key)
        if prev is None:
            by_key[key] = a
            continue

        prev_url = (prev or {}).get("url") or ""
        if is_view_link(prev_url) and not is_view_link(url):
            by_key[key] = a

    # Third pass: group by base and keep best ext (pdf > hwpx > hwp).
    by_base: dict[str, dict] = {}
    for (base, ext), a in by_key.items():
        url = (a or {}).get("url") or ""
        ext_norm = (ext or "").lower().lstrip(".")

        prev = by_base.get(base)
        if prev is None:
            by_base[base] = a
            continue

        prev_ext = attachment_key((prev or {}).get("url") or "", title=(prev or {}).get("title"))[1]
        if priority.get(ext_norm, 0) > priority.get(prev_ext, 0):
            by_base[base] = a
        else:
            # Same ext: prefer download-ish link
            if is_view_link((prev or {}).get("url") or "") and not is_view_link(url):
                by_base[base] = a

    # Preserve original-ish order by walking cleaned list and selecting winners.
    winners = {id(v): v for v in by_base.values()}
    out: list[dict] = []
    seen: set[int] = set()
    for a in cleaned:
        # find the chosen attachment for this base
        base, _ext = attachment_key((a or {}).get("url") or "", title=(a or {}).get("title"))
        chosen = by_base.get(base)
        if chosen is None:
            continue
        cid = id(chosen)
        if cid in seen:
            continue
        if cid in winners:
            out.append(chosen)
            seen.add(cid)

    return out


def _load_exported_site_ids_from_repo(repo_root: str) -> set[str]:
    """Build a set of "source:site_id" from tracked markdown under docs/items.

    Designed for stateless CI where SQLite is empty but the repo already contains
    exported item pages.

    We intentionally parse from path (docs/items/<source>/YYYY/MM/<site_id>.md)
    to avoid needing to parse frontmatter.
    """

    docs_items = os.path.join(repo_root, "docs", "items")
    if not os.path.exists(docs_items):
        return set()

    out: set[str] = set()
    for root, _dirs, files in os.walk(docs_items):
        for fn in files:
            if not fn.endswith(".md"):
                continue
            path = os.path.join(root, fn)
            rel = os.path.relpath(path, docs_items)
            parts = rel.split(os.sep)
            # Expected: <source>/<YYYY>/<MM>/<site_id>.md
            if len(parts) < 4:
                continue
            src = parts[0]
            site_id = os.path.splitext(parts[-1])[0]
            if src and site_id:
                out.add(f"{src}:{site_id}")
    return out


def _iter_items_any(args: argparse.Namespace):
    """Prefer SQLite; fallback to JSONL if requested or DB missing.

    Default behavior: apply plant-only filtering (exclude obvious animal/livestock/pet posts).
    """
    db_path = getattr(args, "db", None)
    jsonl_path = getattr(args, "jsonl", None)

    if db_path and os.path.exists(db_path):
        store = SqliteStore(db_path)
        for it in store.iter_items(sources=list(args.sources) if getattr(args, "sources", None) else None):
            d = decide_plant_only(title=it.get("title") or "", content_text=it.get("content_text") or "", tags=it.get("tags") or [])
            if d.keep:
                yield it
        return

    if jsonl_path and os.path.exists(jsonl_path):
        import json

        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                it = json.loads(line)
                d = decide_plant_only(title=it.get("title") or "", content_text=it.get("content_text") or "", tags=it.get("tags") or [])
                if d.keep:
                    yield it
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
    all_sources = sorted(SOURCES.keys())

    idx = write_index_portal(items, outdir=args.outdir, days=args.days, limit=args.limit, all_sources=all_sources)
    src_paths = write_source_indexes(items, outdir=args.outdir, all_sources=all_sources)

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
    pr.add_argument(
        "--sources",
        nargs="+",
        default=["rda", "nics", "nihhs", "seedworld", "sciencedaily"],
        help="Sources to run",
    )
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
