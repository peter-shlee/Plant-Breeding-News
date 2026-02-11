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


def _truncate_title(s: str, *, max_chars: int = 110) -> str:
    s = (s or "").strip()
    if len(s) <= max_chars:
        return s
    return s[: max(0, max_chars - 1)].rstrip() + "…"


def _item_excerpt(it: dict[str, Any], *, max_len: int = 200) -> str:
    """Source-agnostic excerpt.

    We prefer explicit `summary` if present. Otherwise, fall back to the first
    meaningful line of `content_text`.

    This avoids the UI looking "uneven" when only some sources populate summary.
    """

    summary = (it.get("summary") or "").strip()
    if summary:
        s = summary
    else:
        ct = (it.get("content_text") or "").strip()
        if not ct:
            return ""
        lines = [ln.strip() for ln in ct.splitlines()]
        lines = [ln for ln in lines if ln]
        if not lines:
            return ""
        s = lines[0]

    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > max_len:
        s = s[: max_len - 1].rstrip() + "…"
    return s


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
    lines.append(f"summary: {_yaml_quote(item.get('summary') or '')}")
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
    if url:
        parts.append(f"- [원문 링크]({url})\n")
    else:
        parts.append("- (원문 링크 없음)\n")

    return "\n".join(parts).rstrip() + "\n"


def _write_md_if_changed(path: str, md: str) -> bool:
    """Write md to path if different. Returns True if written."""
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                if f.read() == md:
                    return False
        except Exception:
            pass
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(md)
    return True


def export_md_items(
    items: Iterable[dict[str, Any]],
    *,
    outdir: str,
    days: int,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Export item pages for items newer than cutoff (last N days)."""
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
        md = render_item_md(item)
        if _write_md_if_changed(path, md):
            written += 1

    return {"considered": considered, "written": written, "cutoff": cutoff.isoformat(timespec="seconds")}


def export_md_all_items(items: Iterable[dict[str, Any]], *, outdir: str) -> dict[str, Any]:
    """Export item pages for ALL items (no cutoff)."""
    written = 0
    considered = 0
    for item in items:
        considered += 1
        rel = item_relpath(item)
        path = os.path.join(outdir, rel)
        md = render_item_md(item)
        if _write_md_if_changed(path, md):
            written += 1
    return {"considered": considered, "written": written}


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
    lines.append(f"title: { _yaml_quote('주간 요약') }")
    lines.append(f"range_start: {_yaml_quote(w.range_start)}")
    lines.append(f"range_end: {_yaml_quote(w.range_end)}")
    lines.append("---\n")

    lines.append(f"# 주간 요약 ({w.range_start} ~ {w.range_end})\n")

    lines.append(f"## Recent (last {w.days} days)\n")
    if not w.items:
        lines.append("(No items.)\n")
    else:
        for it in w.items:
            title_full = (it.get("title") or it.get("site_id") or it.get("id") or "Item").strip()
            title = _truncate_title(title_full, max_chars=110)
            src = (it.get("source") or "unknown").strip()
            item_link = rel_item_link(it)
            url = it.get("url") or ""
            excerpt = _item_excerpt(it)

            lines.append(f"- **[{title}]({item_link})**")
            lines.append(f"  - {fmt_dt(it)} · `{src}` · [읽기]({item_link})" + (f" · [원문]({url})" if url else ""))
            if excerpt:
                lines.append(f"  - {excerpt}")
            lines.append("")
        lines.append("")

    lines.append("## By source\n")
    by_source: dict[str, list[dict[str, Any]]] = {}
    for it in w.items:
        by_source.setdefault(it.get("source") or "unknown", []).append(it)

    for src in sorted(by_source.keys()):
        lines.append(f"### {src}\n")
        for it in by_source[src]:
            title_full = (it.get("title") or it.get("site_id") or it.get("id") or "Item").strip()
            title = _truncate_title(title_full, max_chars=110)
            item_link = rel_item_link(it)
            url = it.get("url") or ""
            excerpt = _item_excerpt(it)

            lines.append(f"- **[{title}]({item_link})**")
            lines.append(f"  - {fmt_dt(it)} · [읽기]({item_link})" + (f" · [원문]({url})" if url else ""))
            if excerpt:
                lines.append(f"  - {excerpt}")
            lines.append("")
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


def _list_weekly_archive(*, outdir: str) -> list[str]:
    """Return weekly archive filenames (YYYY-MM-DD.md), newest first."""
    weekly_dir = os.path.join(outdir, "weekly")
    if not os.path.exists(weekly_dir):
        return []

    archive: list[str] = []
    for name in os.listdir(weekly_dir):
        if not name.endswith(".md"):
            continue
        if name == "latest.md":
            continue
        # keep only dated pages
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.md", name):
            archive.append(name)

    archive.sort(reverse=True)
    return archive


def _fmt_date_ymd(it: dict[str, Any]) -> str:
    s = (it.get("published_at") or it.get("fetched_at") or "")
    if not s:
        return ""
    return s.split("T")[0]


def render_portal_index_md(
    items: list[dict[str, Any]],
    *,
    outdir: str,
    days: int,
    limit: int = 25,
    now: Optional[datetime] = None,
    all_sources: Optional[list[str]] = None,
) -> str:
    """Generate docs/index.md portal page.

    - Recent items: last N days, newest first.
    - Weekly archive links: weekly/YYYY-MM-DD.md
    - Per-source archive links: sources/<src>/index.md
    """

    now_kst = _kst_today(now=now)
    cutoff = now_kst - timedelta(days=days)

    def sort_key(it: dict[str, Any]):
        dt = _parse_dt(it.get("published_at")) or _parse_dt(it.get("fetched_at"))
        return dt or datetime.min

    recent: list[dict[str, Any]] = []
    for it in items:
        dt = _parse_dt(it.get("published_at")) or _parse_dt(it.get("fetched_at"))
        if dt is not None:
            try:
                dt_kst = dt.astimezone(now_kst.tzinfo)
            except Exception:
                dt_kst = dt
            if dt_kst < cutoff:
                continue
        recent.append(it)

    recent.sort(key=sort_key, reverse=True)
    recent = recent[: max(0, limit)]

    weekly_archive = _list_weekly_archive(outdir=outdir)

    sources = sorted(all_sources) if all_sources else sorted({(it.get("source") or "unknown") for it in items})

    updated_at = now_kst.strftime("%Y-%m-%d %H:%M")
    range_end = now_kst.date().isoformat()
    range_start = (now_kst - timedelta(days=days)).date().isoformat()

    def rel_item_link(it: dict[str, Any]) -> str:
        return item_relpath(it).replace(os.sep, "/")

    lines: list[str] = []
    lines.append("---")
    lines.append(f"title: {_yaml_quote('식물 육종 뉴스')}")
    lines.append("---\n")

    lines.append("# 식물 육종 뉴스\n")
    lines.append("종자·품종·작물(식물) 관련 보도자료/공지 링크를 모아둔 자동 생성 페이지입니다.\n")
    lines.append("> 이 페이지와 하위 문서는 스크립트로 자동 생성됩니다. 수동 편집하지 마세요.\n")
    lines.append(
        f"- 마지막 업데이트: **{updated_at} (KST)**  " + "\n"
        + f"- 커버리지(최근 섹션): **{range_start} ~ {range_end}** (최근 {days}일)\n"
    )

    # TOC (main page only)
    lines.append("## 목차\n")
    lines.append("- [이번주 하이라이트](#highlights)")
    lines.append("- [최근 소식](#recent)")
    lines.append("- [지난 주간 아카이브](#weekly-archive)")
    lines.append("- [출처별 모아보기](#sources)\n")

    # --- 핵심 섹션 (최근 7일, 키워드 기반 스코어링) ---
    core_cutoff = now_kst - timedelta(days=7)

    CORE_BOOST_KWS = [
        "육종",
        "품종",
        "신품종",
        "종자",
        "계통",
        "교배",
        "SNP",
        "마커",
        "KASP",
        "유전체",
        "표현체",
        "내병성",
        "CRISPR",
        "품종보호",
        "UPOV",
        "variety protection",
        "marker",
        "genomics",
        "phenotyping",
        "gene editing",
    ]

    # Light penalty for generic admin/policy/newsroom posts
    CORE_PENALTY_KWS = [
        "채용",
        "모집",
        "공고",
        "입찰",
        "회의",
        "위원회",
        "설명회",
        "행사",
        "업무협약",
        "mou",
        "정책",
        "계획",
        "예산",
    ]

    def core_score(it: dict[str, Any]) -> float:
        text = " ".join([
            (it.get("title") or ""),
            (it.get("summary") or ""),
            (it.get("content_text") or ""),
            " ".join(it.get("tags") or []),
        ])
        t = re.sub(r"\s+", " ", text.lower()).strip()
        score = 0.0
        hits = 0
        for kw in CORE_BOOST_KWS:
            k = kw.lower()
            if not k:
                continue
            if re.fullmatch(r"[a-z0-9 ]+", k):
                pat = r"\b" + re.escape(k).replace(r"\ ", r"\s+") + r"\b"
                if re.search(pat, t):
                    hits += 1
            else:
                if k in t:
                    hits += 1
        score += hits * 2.0

        p_hits = 0
        for kw in CORE_PENALTY_KWS:
            k = kw.lower()
            if not k:
                continue
            if re.fullmatch(r"[a-z0-9 ]+", k):
                if re.search(r"\b" + re.escape(k) + r"\b", t):
                    p_hits += 1
            else:
                if k in t:
                    p_hits += 1
        score -= p_hits * 0.75

        # Small bonus if technique tags are present
        tech_bonus = 0
        for tg in (it.get("tags") or []):
            if tg in {"genomics", "marker", "gene-editing", "phenotyping", "IP-policy"}:
                tech_bonus += 1
        score += tech_bonus * 0.5

        return score

    core_candidates: list[dict[str, Any]] = []
    for it in items:
        dt = _parse_dt(it.get("published_at")) or _parse_dt(it.get("fetched_at"))
        if dt is not None:
            try:
                dt_kst = dt.astimezone(now_kst.tzinfo)
            except Exception:
                dt_kst = dt
            if dt_kst < core_cutoff:
                continue
        core_candidates.append(it)

    core_scored = [(core_score(it), it) for it in core_candidates]
    core_scored.sort(key=lambda x: (x[0], _parse_dt(x[1].get("published_at")) or _parse_dt(x[1].get("fetched_at")) or datetime.min), reverse=True)

    desired_n = 10
    if len(core_scored) >= 12:
        core_n = 12
    elif len(core_scored) >= 10:
        core_n = 10
    elif len(core_scored) >= 8:
        core_n = 8
    else:
        core_n = len(core_scored)

    lines.append('<a id="highlights"></a>')
    lines.append("## 이번주 하이라이트 (육종/품종/종자)\n")
    lines.append("최근 7일 중에서 ‘육종/품종/종자’ 관련 키워드 신호가 강한 소식을 우선 정리했습니다.\n")
    if not core_scored:
        lines.append("(최근 7일 내 하이라이트로 뽑을 만한 항목이 없습니다.)\n")
    else:
        for sc, it in core_scored[:core_n]:
            title_full = (it.get("title") or it.get("site_id") or it.get("id") or "Item").strip()
            title = _truncate_title(title_full, max_chars=110)
            src = (it.get("source") or "unknown").strip()
            url = it.get("url") or ""
            item_link = rel_item_link(it)
            excerpt = _item_excerpt(it)

            lines.append(f"- **[{title}]({item_link})**")
            lines.append(f"  - {_fmt_date_ymd(it)} · `{src}` · [읽기]({item_link})" + (f" · [원문]({url})" if url else ""))
            if excerpt:
                lines.append(f"  - {excerpt}")
            lines.append("")
        lines.append("")

    lines.append('<a id="recent"></a>')
    lines.append("## 최근 소식 (최근 7일)\n")
    lines.append("최근 7일 이내에 수집된 소식을 최신순으로 보여줍니다.\n")
    if not recent:
        lines.append("(최근 7일 내 새 소식이 없습니다.)\n")
    else:
        for it in recent:
            title_full = (it.get("title") or it.get("site_id") or it.get("id") or "Item").strip()
            title = _truncate_title(title_full, max_chars=110)
            src = (it.get("source") or "unknown").strip()
            url = it.get("url") or ""
            item_link = rel_item_link(it)
            excerpt = _item_excerpt(it)

            lines.append(f"- **[{title}]({item_link})**")
            lines.append(f"  - {_fmt_date_ymd(it)} · `{src}` · [읽기]({item_link})" + (f" · [원문]({url})" if url else ""))
            if excerpt:
                lines.append(f"  - {excerpt}")
            lines.append("")
        lines.append("")

    lines.append('<a id="weekly-archive"></a>')
    lines.append("## 지난 주간 아카이브\n")
    lines.append("주간 단위로 묶어둔 페이지입니다. (자동 생성)\n")
    if not weekly_archive:
        lines.append("(아직 생성된 주간 페이지가 없습니다.)\n")
    else:
        for name in weekly_archive:
            date = name.replace(".md", "")
            lines.append(f"- [{date}](weekly/{name})")
        lines.append("")

    lines.append('<a id="sources"></a>')
    lines.append("## 출처별 모아보기\n")
    lines.append("원하는 출처만 골라서 전체 목록을 볼 수 있습니다.\n")
    for src in sources:
        src_slug = _safe_slug(src)
        lines.append(f"- [{src}](sources/{src_slug}/index.md)")
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_index_portal(
    items: list[dict[str, Any]],
    *,
    outdir: str,
    days: int,
    limit: int = 25,
    now: Optional[datetime] = None,
    all_sources: Optional[list[str]] = None,
) -> str:
    path = os.path.join(outdir, "index.md")
    md = render_portal_index_md(items, outdir=outdir, days=days, limit=limit, now=now, all_sources=all_sources)
    with open(path, "w", encoding="utf-8") as f:
        f.write(md)
    return os.path.relpath(path, outdir)


def render_source_index_md(
    src: str,
    items: list[dict[str, Any]],
    *,
    outdir: str,
) -> str:
    """Generate docs/sources/<src>/index.md grouped by month."""

    # source index path: sources/<src>/index.md
    # links from there to items live at ../../items/...
    def rel_item_link(it: dict[str, Any]) -> str:
        return os.path.join("..", "..", item_relpath(it)).replace(os.sep, "/")

    def sort_key(it: dict[str, Any]):
        dt = _parse_dt(it.get("published_at")) or _parse_dt(it.get("fetched_at"))
        return dt or datetime.min

    items_sorted = list(items)
    items_sorted.sort(key=sort_key, reverse=True)

    by_month: dict[str, list[dict[str, Any]]] = {}
    for it in items_sorted:
        dt = _parse_dt(it.get("published_at")) or _parse_dt(it.get("fetched_at"))
        if dt is None:
            key = "0000-00"
        else:
            key = f"{dt.year:04d}-{dt.month:02d}"
        by_month.setdefault(key, []).append(it)

    months = sorted(by_month.keys(), reverse=True)

    lines: list[str] = []
    lines.append("---")
    lines.append(f"title: {_yaml_quote(f'{src} 아카이브')}")
    lines.append(f"source: {_yaml_quote(src)}")
    lines.append("---\n")

    lines.append(f"# {src} 아카이브\n")
    lines.append("> 이 문서는 스크립트로 자동 생성됩니다. 수동 편집하지 마세요.\n")
    lines.append("- [홈으로](../../index.md)\n")

    if not months:
        lines.append("(No items.)\n")

    for m in months:
        lines.append(f"## {m}\n")
        for it in by_month[m]:
            title_full = (it.get("title") or it.get("site_id") or it.get("id") or "Item").strip()
            title = _truncate_title(title_full, max_chars=110)
            url = it.get("url") or ""
            item_link = rel_item_link(it)
            excerpt = _item_excerpt(it)

            lines.append(f"- **[{title}]({item_link})**")
            lines.append(f"  - {_fmt_date_ymd(it)} · [읽기]({item_link})" + (f" · [원문]({url})" if url else ""))
            if excerpt:
                lines.append(f"  - {excerpt}")
            lines.append("")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_source_indexes(
    items: list[dict[str, Any]],
    *,
    outdir: str,
    all_sources: Optional[list[str]] = None,
) -> list[str]:
    written: list[str] = []

    by_source: dict[str, list[dict[str, Any]]] = {}
    for it in items:
        by_source.setdefault(it.get("source") or "unknown", []).append(it)

    # Ensure stable presence of configured sources even if there are no items yet.
    if all_sources:
        for src in all_sources:
            by_source.setdefault(src, [])

    for src, src_items in sorted(by_source.items(), key=lambda kv: kv[0]):
        src_slug = _safe_slug(src)
        dirpath = os.path.join(outdir, "sources", src_slug)
        os.makedirs(dirpath, exist_ok=True)
        path = os.path.join(dirpath, "index.md")
        md = render_source_index_md(src, src_items, outdir=outdir)
        with open(path, "w", encoding="utf-8") as f:
            f.write(md)
        written.append(os.path.relpath(path, outdir))

    return written
