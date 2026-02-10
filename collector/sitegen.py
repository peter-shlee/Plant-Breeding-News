from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable, Optional

from dateutil import parser


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return parser.isoparse(s)
    except Exception:
        try:
            return parser.parse(s, fuzzy=True)
        except Exception:
            return None


def _cutoff_dt(days: int, now: Optional[datetime] = None) -> datetime:
    now_dt = now or datetime.now().astimezone()
    return now_dt - timedelta(days=days)


def _safe_slug(s: str) -> str:
    s = (s or "").strip()
    # keep alnum, dash, underscore; replace others
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", s)
    return s or "item"


def _yaml_quote(s: Any) -> str:
    if s is None:
        return "\"\""
    if isinstance(s, (int, float)):
        return str(s)
    s = str(s)
    s = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def _yaml_list(lines: list[str], key: str, values: list[Any]) -> None:
    if not values:
        lines.append(f"{key}: []")
        return
    lines.append(f"{key}:")
    for v in values:
        lines.append(f"  - {_yaml_quote(v)}")


def _frontmatter(item: dict[str, Any]) -> str:
    atts = []
    for a in item.get("attachments") or []:
        if isinstance(a, str):
            url = a
        else:
            url = (a or {}).get("url")
        if url:
            atts.append(url)

    lines: list[str] = ["---"]
    # Required keys
    lines.append(f"id: {_yaml_quote(item.get('id'))}")
    lines.append(f"source: {_yaml_quote(item.get('source'))}")
    lines.append(f"org: {_yaml_quote(item.get('org'))}")
    lines.append(f"site_id: {_yaml_quote(item.get('site_id'))}")
    lines.append(f"published_at: {_yaml_quote(item.get('published_at'))}")
    lines.append(f"url: {_yaml_quote(item.get('url'))}")
    _yaml_list(lines, "attachments", atts)
    _yaml_list(lines, "tags", item.get("tags") or [])
    lines.append(f"fetched_at: {_yaml_quote(item.get('fetched_at'))}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def item_relpath(item: dict[str, Any]) -> str:
    src = _safe_slug(item.get("source") or "unknown")
    site_id = _safe_slug(item.get("site_id") or item.get("id") or "item")

    dt = _parse_dt(item.get("published_at")) or _parse_dt(item.get("fetched_at"))
    if dt is None:
        # fallback bucket
        year = "0000"
        month = "00"
    else:
        year = f"{dt.year:04d}"
        month = f"{dt.month:02d}"

    return os.path.join("items", src, year, month, f"{site_id}.md")


def render_item_md(item: dict[str, Any]) -> str:
    title = (item.get("title") or "").strip() or (item.get("site_id") or item.get("id") or "Item")
    content_text = (item.get("content_text") or "").strip()
    summary = (item.get("summary") or "").strip()  # not in schema, but tolerate
    body_text = content_text or summary or "(No content_text available.)"
    url = item.get("url") or ""

    parts: list[str] = []
    parts.append(_frontmatter(item).rstrip())
    parts.append(f"# {title}\n")
    parts.append(body_text + "\n")
    parts.append("## Original\n")
    parts.append(f"- {url}\n")

    return "\n".join(parts).rstrip() + "\n"


def export_md_items(
    items: Iterable[dict[str, Any]],
    *,
    outdir: str,
    days: int,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    cutoff = _cutoff_dt(days, now=now)

    written = 0
    considered = 0
    for item in items:
        considered += 1
        dt = _parse_dt(item.get("published_at")) or _parse_dt(item.get("fetched_at"))
        if dt is not None and dt < cutoff:
            continue

        rel = item_relpath(item)
        path = os.path.join(outdir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        md = render_item_md(item)

        # Write only if changed
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    if f.read() == md:
                        continue
            except Exception:
                pass

        with open(path, "w", encoding="utf-8") as f:
            f.write(md)
        written += 1

    return {"considered": considered, "written": written, "cutoff": cutoff.isoformat(timespec="seconds")}


@dataclass
class WeeklyBuild:
    run_date: str  # YYYY-MM-DD (KST local date)
    days: int
    range_start: str
    range_end: str
    items: list[dict[str, Any]]


def _kst_today(now: Optional[datetime] = None) -> datetime:
    from zoneinfo import ZoneInfo

    base = now or datetime.now().astimezone()
    return base.astimezone(ZoneInfo("Asia/Seoul"))


def prepare_weekly(items: Iterable[dict[str, Any]], *, days: int, now: Optional[datetime] = None) -> WeeklyBuild:
    now_kst = _kst_today(now=now)
    cutoff = now_kst - timedelta(days=days)

    collected: list[dict[str, Any]] = []
    for it in items:
        dt = _parse_dt(it.get("published_at")) or _parse_dt(it.get("fetched_at"))
        if dt is not None:
            # compare in KST for "last N days" semantics
            try:
                dt_kst = dt.astimezone(now_kst.tzinfo)
            except Exception:
                dt_kst = dt
            if dt_kst < cutoff:
                continue
        collected.append(it)

    def sort_key(it: dict[str, Any]):
        dt = _parse_dt(it.get("published_at")) or _parse_dt(it.get("fetched_at"))
        return dt or datetime.min

    collected.sort(key=sort_key, reverse=True)

    run_date = now_kst.date().isoformat()
    range_end = now_kst.date().isoformat()
    range_start = (now_kst - timedelta(days=days)).date().isoformat()
    return WeeklyBuild(run_date=run_date, days=days, range_start=range_start, range_end=range_end, items=collected)


def render_weekly_md(w: WeeklyBuild, *, outdir: str) -> str:
    # Links are relative to site root; weekly pages live in site/weekly/
    def rel_item_link(it: dict[str, Any]) -> str:
        return os.path.join("..", item_relpath(it)).replace(os.sep, "/")

    def fmt_dt(it: dict[str, Any]) -> str:
        return (it.get("published_at") or it.get("fetched_at") or "").split("T")[0]

    lines: list[str] = []
    lines.append("---")
    lines.append(f"title: { _yaml_quote('Weekly digest') }")
    lines.append(f"range_start: {_yaml_quote(w.range_start)}")
    lines.append(f"range_end: {_yaml_quote(w.range_end)}")
    lines.append("---\n")

    lines.append(f"# Weekly digest ({w.range_start} to {w.range_end})\n")

    lines.append(f"## Recent (last {w.days} days)\n")
    if not w.items:
        lines.append("(No items.)\n")
    else:
        for it in w.items:
            title = (it.get("title") or it.get("site_id") or it.get("id") or "Item").strip()
            item_link = rel_item_link(it)
            url = it.get("url") or ""
            lines.append(f"- {fmt_dt(it)} [{title}]({item_link}) ([original]({url}))")
        lines.append("")

    lines.append("## By source\n")
    by_source: dict[str, list[dict[str, Any]]] = {}
    for it in w.items:
        by_source.setdefault(it.get("source") or "unknown", []).append(it)

    for src in sorted(by_source.keys()):
        lines.append(f"### {src}\n")
        for it in by_source[src]:
            title = (it.get("title") or it.get("site_id") or it.get("id") or "Item").strip()
            item_link = rel_item_link(it)
            url = it.get("url") or ""
            lines.append(f"- {fmt_dt(it)} [{title}]({item_link}) ([original]({url}))")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_weekly_pages(w: WeeklyBuild, *, outdir: str) -> dict[str, Any]:
    weekly_dir = os.path.join(outdir, "weekly")
    os.makedirs(weekly_dir, exist_ok=True)

    dated_name = f"{w.run_date}.md"
    latest_path = os.path.join(weekly_dir, "latest.md")
    dated_path = os.path.join(weekly_dir, dated_name)

    md = render_weekly_md(w, outdir=outdir)

    for p in (latest_path, dated_path):
        with open(p, "w", encoding="utf-8") as f:
            f.write(md)

    return {"latest": os.path.relpath(latest_path, outdir), "dated": os.path.relpath(dated_path, outdir)}


def render_index_md(*, outdir: str) -> str:
    weekly_dir = os.path.join(outdir, "weekly")
    os.makedirs(weekly_dir, exist_ok=True)

    # archive: all weekly/*.md except latest
    archive: list[str] = []
    for name in os.listdir(weekly_dir):
        if not name.endswith(".md"):
            continue
        if name == "latest.md":
            continue
        archive.append(name)

    # sort desc by filename (YYYY-MM-DD)
    archive.sort(reverse=True)

    lines: list[str] = []
    lines.append("---")
    lines.append("title: \"Breeding news digest\"")
    lines.append("---\n")
    lines.append("# Breeding news digest\n")
    lines.append("- [Latest weekly](weekly/latest.md)\n")
    lines.append("## Weekly archive\n")
    if not archive:
        lines.append("(No archive yet.)\n")
    else:
        for name in archive:
            lines.append(f"- [{name.replace('.md','')}]({os.path.join('weekly', name).replace(os.sep,'/')})")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_index(*, outdir: str) -> str:
    path = os.path.join(outdir, "index.md")
    md = render_index_md(outdir=outdir)
    with open(path, "w", encoding="utf-8") as f:
        f.write(md)
    return os.path.relpath(path, outdir)
