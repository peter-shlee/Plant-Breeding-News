from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Optional


BRIEFING_START = "<!-- AUTO_BRIEFING_START -->"
BRIEFING_END = "<!-- AUTO_BRIEFING_END -->"


@dataclass
class RecentItem:
    idx: int
    date: str
    source: str
    title: str
    item_path: str  # relative markdown path, e.g. items/rda/...
    original_url: str
    excerpt: str


def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _write_text(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _extract_existing_briefing(md: str) -> str:
    m = re.search(re.escape(BRIEFING_START) + r".*?" + re.escape(BRIEFING_END), md, flags=re.S)
    return m.group(0).strip() if m else ""


def _strip_frontmatter(md: str) -> str:
    if md.startswith("---"):
        end = md.find("\n---", 3)
        if end != -1:
            return md[end + len("\n---") :].lstrip("\n")
    return md


def _extract_item_excerpt(item_md_path: str, *, max_chars: int = 800) -> str:
    try:
        md = _read_text(item_md_path)
    except Exception:
        return ""

    md = _strip_frontmatter(md)
    # Remove heading line
    md = re.sub(r"^#\s+.*\n", "", md)
    # Stop before Original section
    md = md.split("\n## Original\n", 1)[0]
    # Collapse whitespace
    md = re.sub(r"\s+", " ", md).strip()
    if not md:
        return ""
    if len(md) > max_chars:
        md = md[: max_chars - 1].rstrip() + "…"
    return md


_RECENT_ITEM_RE = re.compile(
    r"^-\s+(?P<date>\d{4}-\d{2}-\d{2})\s+\[(?P<src>[^\]]+)\]\s+\[(?P<title>[^\]]+)\]\((?P<item>[^\)]+)\)\s+\(\[원문\]\((?P<orig>[^\)]+)\)\)",
    re.M,
)


def parse_recent_items_from_index(index_md: str, *, docs_root: str, max_items: int = 30) -> list[RecentItem]:
    """Parse the '최근 소식 (최근 7일)' section from docs/index.md.

    We intentionally ONLY use the list already rendered on the GitHub Pages index.
    """

    # Narrow to '최근 소식' section
    if "## 최근 소식 (최근 7일)" not in index_md:
        return []

    after = index_md.split("## 최근 소식 (최근 7일)", 1)[1]
    # Stop at next h2
    after = re.split(r"\n##\s+", after, maxsplit=1)[0]

    items: list[RecentItem] = []
    for m in _RECENT_ITEM_RE.finditer(after):
        if len(items) >= max_items:
            break
        date = m.group("date").strip()
        src = m.group("src").strip()
        title = m.group("title").strip()
        item_path = m.group("item").strip()
        orig = m.group("orig").strip()

        item_fs_path = os.path.join(docs_root, item_path)
        excerpt = _extract_item_excerpt(item_fs_path, max_chars=800)

        items.append(
            RecentItem(
                idx=len(items) + 1,
                date=date,
                source=src,
                title=title,
                item_path=item_path,
                original_url=orig,
                excerpt=excerpt,
            )
        )

    return items


def parse_range_from_index(index_md: str) -> tuple[str, str]:
    """Parse range_start, range_end from docs/index.md metadata lines.

    Expected format:
    - 커버리지(최근 섹션): **YYYY-MM-DD ~ YYYY-MM-DD** (최근 7일)
    """

    m = re.search(r"커버리지\(최근 섹션\):\s*\*\*(\d{4}-\d{2}-\d{2})\s*~\s*(\d{4}-\d{2}-\d{2})\*\*", index_md)
    if not m:
        return ("", "")
    return (m.group(1), m.group(2))


def build_gemini_prompt(items: list[RecentItem], *, range_start: str, range_end: str) -> str:
    # Keep prompt concise but strict.
    lines: list[str] = []
    lines.append("너는 '식물 육종 뉴스' 메인 페이지의 주간 브리핑 편집자다.")
    lines.append("아래에 제공된 기사 목록에서만 선택해 30초 분량의 주간 브리핑을 만들어라.")
    lines.append("반드시 한국어로 작성하고, 영문 기사도 한국어로 요약하라.")
    lines.append("")
    lines.append("[중요 규칙]")
    lines.append("- 기사 선택은 제공된 목록의 idx만 사용한다. 목록에 없는 기사/링크를 만들지 마라.")
    lines.append("- 축은 3개: policy(정책/규제), research(연구/기술), market(유통/시장/현장)")
    lines.append("- 각 축에서 가장 중요한 기사 2개씩 총 6개를 고른다.")
    lines.append("- 각 기사 요약(summary)은 1~2문장, 한국어, 과장 없이 사실 기반으로 쓴다.")
    lines.append("- 전체는 30초 내 읽을 수 있게 간결하게(대략 900~1200자 수준) 만든다.")
    lines.append("")
    lines.append("[출력 형식: JSON만 출력]")
    lines.append("{")
    lines.append('  "range": "YYYY-MM-DD~YYYY-MM-DD",')
    lines.append('  "policy": [{"idx": 1, "summary": "..."}, {"idx": 2, "summary": "..."}],')
    lines.append('  "research": [{"idx": 3, "summary": "..."}, {"idx": 4, "summary": "..."}],')
    lines.append('  "market": [{"idx": 5, "summary": "..."}, {"idx": 6, "summary": "..."}],')
    lines.append('  "one_liner": "이번 주 한줄 요약(선택)"')
    lines.append("}")
    lines.append("")
    lines.append(f"[기간] {range_start}~{range_end}")
    lines.append("[기사 목록]")
    for it in items:
        # Provide excerpt (may be empty).
        excerpt = it.excerpt or "(본문 발췌 없음)"
        lines.append(f"- idx={it.idx} | date={it.date} | source={it.source}")
        lines.append(f"  title: {it.title}")
        lines.append(f"  item_path: {it.item_path}")
        lines.append(f"  original_url: {it.original_url}")
        lines.append(f"  excerpt: {excerpt}")
    return "\n".join(lines).strip() + "\n"


def _call_gemini_generate_json(prompt: str, *, api_key: str, model: str = "gemini-2.5-flash", timeout_s: int = 60) -> dict[str, Any]:
    """Call Gemini generateContent.

    Uses direct HTTP to avoid extra deps.
    """

    import requests

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    headers = {
        "x-goog-api-key": api_key,
        "Content-Type": "application/json",
    }
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.4,
            "maxOutputTokens": 900,
            "responseMimeType": "application/json",
        },
    }

    r = requests.post(url, headers=headers, json=payload, timeout=timeout_s)
    if r.status_code >= 400:
        raise RuntimeError(f"Gemini HTTP {r.status_code}: {r.text[:300]}")
    data = r.json()

    # Extract text from first candidate
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        raise RuntimeError(f"Gemini response missing candidate text: {json.dumps(data)[:500]}")

    try:
        return json.loads(text)
    except Exception:
        # Sometimes it returns plain JSON without being valid due to trailing text.
        m = re.search(r"\{.*\}", text, flags=re.S)
        if m:
            return json.loads(m.group(0))
        raise


def _render_briefing_md(result: dict[str, Any], *, items_by_idx: dict[int, RecentItem]) -> str:
    def render_axis(title: str, key: str) -> list[str]:
        out: list[str] = []
        out.append(f"### {title}\n")
        arr = result.get(key) or []
        for obj in arr:
            idx = int(obj.get("idx"))
            summ = (obj.get("summary") or "").strip()
            it = items_by_idx.get(idx)
            if not it:
                continue
            # We control links to avoid hallucinations.
            out.append(
                f"- [{it.title}]({it.item_path}) ([원문]({it.original_url})) — {summ}"
            )
        out.append("")
        return out

    range_str = (result.get("range") or "").strip() or "주간"

    lines: list[str] = []
    lines.append(BRIEFING_START)
    lines.append(f"## 30초 주간 브리핑 ({range_str})\n")

    one_liner = (result.get("one_liner") or "").strip()
    if one_liner:
        lines.append(f"> {one_liner}\n")

    lines += render_axis("1) 정책/규제", "policy")
    lines += render_axis("2) 연구/기술", "research")
    lines += render_axis("3) 유통/시장/현장", "market")

    lines.append(BRIEFING_END)
    return "\n".join(lines).rstrip() + "\n"


def insert_briefing_into_index(index_md: str, briefing_block: str) -> str:
    if not briefing_block.strip():
        return index_md

    # Remove existing block if any.
    index_md2 = re.sub(
        re.escape(BRIEFING_START) + r".*?" + re.escape(BRIEFING_END) + r"\n?",
        "",
        index_md,
        flags=re.S,
    )

    # Insert before '이번주 하이라이트'
    anchor = "## 이번주 하이라이트 (육종/품종/종자)"
    if anchor not in index_md2:
        # fallback: insert after metadata bullet list (after coverage line)
        return index_md2.rstrip() + "\n\n" + briefing_block.strip() + "\n"

    before, after = index_md2.split(anchor, 1)

    # Ensure spacing
    before = before.rstrip() + "\n\n" + briefing_block.strip() + "\n\n"
    return before + anchor + after


def build_or_fallback_briefing(
    *,
    docs_dir: str,
    index_path: str,
    fallback_index_path: Optional[str] = None,
    range_start: str,
    range_end: str,
    max_items: int = 30,
    model: str = "gemini-2.5-flash",
) -> dict[str, Any]:
    """Build briefing and inject into docs/index.md.

    If GEMINI_API_KEY is missing or API fails, try to keep previous briefing block from fallback_index_path.
    """

    index_md = _read_text(index_path)

    # Auto range parsing from index if not provided
    if not range_start or not range_end:
        rs, re_ = parse_range_from_index(index_md)
        range_start = range_start or rs
        range_end = range_end or re_
        if not range_start or not range_end:
            # Fallback to unknown range (still ok)
            range_start = range_start or ""
            range_end = range_end or ""

    items = parse_recent_items_from_index(index_md, docs_root=docs_dir, max_items=max_items)

    api_key = os.getenv("GEMINI_API_KEY") or ""

    existing_fallback_block = ""
    if fallback_index_path and os.path.exists(fallback_index_path):
        try:
            existing_fallback_block = _extract_existing_briefing(_read_text(fallback_index_path))
        except Exception:
            existing_fallback_block = ""

    if not api_key:
        # No key -> keep previous block if any
        out_md = insert_briefing_into_index(index_md, existing_fallback_block)
        _write_text(index_path, out_md)
        return {"status": "no_api_key", "items": len(items), "used_fallback": bool(existing_fallback_block)}

    if not items:
        out_md = insert_briefing_into_index(index_md, existing_fallback_block)
        _write_text(index_path, out_md)
        return {"status": "no_recent_items", "items": 0, "used_fallback": bool(existing_fallback_block)}

    prompt = build_gemini_prompt(items, range_start=range_start, range_end=range_end)

    try:
        result = _call_gemini_generate_json(prompt, api_key=api_key, model=model)
        items_by_idx = {it.idx: it for it in items}
        briefing_md = _render_briefing_md(result, items_by_idx=items_by_idx)
        out_md = insert_briefing_into_index(index_md, briefing_md)
        _write_text(index_path, out_md)
        return {"status": "ok", "items": len(items), "used_fallback": False}
    except Exception as e:
        # API error -> fallback block
        out_md = insert_briefing_into_index(index_md, existing_fallback_block)
        _write_text(index_path, out_md)
        return {"status": "error", "error": str(e), "items": len(items), "used_fallback": bool(existing_fallback_block)}
