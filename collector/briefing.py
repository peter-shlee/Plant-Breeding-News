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


# Legacy format (older index generator):
# - YYYY-MM-DD [src] [title](items/...) ([원문](...))
_RECENT_ITEM_RE = re.compile(
    r"^-\s+(?P<date>\d{4}-\d{2}-\d{2})\s+\[(?P<src>[^\]]+)\]\s+\[(?P<title>[^\]]+)\]\((?P<item>[^\)]+)\)\s+\(\[원문\]\((?P<orig>[^\)]+)\)\)",
    re.M,
)

# New format (TOC + anchor + rich bullets):
# - **[Title](items/...)**
#   - YYYY-MM-DD · `source` · [읽기](items/...) · [원문](https://...)
_RECENT_BLOCK_TITLE_RE = re.compile(r"^-\s+\*\*\[(?P<title>.+?)\]\((?P<item>items/[^\)]+)\)\*\*\s*$", re.M)
_RECENT_BLOCK_META_RE = re.compile(
    r"^\s+-\s+(?P<date>\d{4}-\d{2}-\d{2})\s+·\s+`(?P<src>[^`]+)`.*?\[원문\]\((?P<orig>[^\)]+)\)",
    re.M,
)


def parse_recent_items_from_index(index_md: str, *, docs_root: str, max_items: int = 30) -> list[RecentItem]:
    """Parse the '최근 소식 (최근 7일)' section from docs/index.md.

    We intentionally ONLY use the list already rendered on the GitHub Pages index.
    """

    # Narrow to '최근 소식' section (be tolerant: header text may vary slightly)
    sec = None
    for header in ("## 최근 소식 (최근 7일)", "## 최근 소식"):
        if header in index_md:
            sec = index_md.split(header, 1)[1]
            break
    if sec is None:
        return []

    # Stop at next h2
    after = re.split(r"\n##\s+", sec, maxsplit=1)[0]

    items: list[RecentItem] = []

    # (1) Try new rich-bullet format
    # Find each title line and look ahead for the first meta line below it.
    title_matches = list(_RECENT_BLOCK_TITLE_RE.finditer(after))
    if title_matches:
        for i, tm in enumerate(title_matches):
            if len(items) >= max_items:
                break
            title = tm.group("title").strip()
            item_path = tm.group("item").strip()

            # search within this block (until next title match or end)
            start = tm.end()
            end = title_matches[i + 1].start() if i + 1 < len(title_matches) else len(after)
            block = after[start:end]
            mm = _RECENT_BLOCK_META_RE.search(block)
            if not mm:
                continue
            date = mm.group("date").strip()
            src = mm.group("src").strip()
            orig = mm.group("orig").strip()

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

    # (2) Fallback to legacy single-line format
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
    lines.append("[출력 형식: 아래 라인 포맷만 출력. JSON/코드블록 금지]")
    lines.append("RANGE: YYYY-MM-DD~YYYY-MM-DD")
    lines.append("ONE_LINER: 한줄 요약(선택)")
    lines.append("POLICY: idx|요약")
    lines.append("POLICY: idx|요약")
    lines.append("RESEARCH: idx|요약")
    lines.append("RESEARCH: idx|요약")
    lines.append("MARKET: idx|요약")
    lines.append("MARKET: idx|요약")
    lines.append("")
    lines.append(f"[기간] {range_start}~{range_end}")
    lines.append("[기사 목록]")
    for it in items:
        excerpt = it.excerpt or "(본문 발췌 없음)"
        lines.append(f"- idx={it.idx} | date={it.date} | source={it.source}")
        lines.append(f"  title: {it.title}")
        lines.append(f"  item_path: {it.item_path}")
        lines.append(f"  original_url: {it.original_url}")
        lines.append(f"  excerpt: {excerpt}")
    return "\n".join(lines).strip() + "\n"


def _call_gemini_generate_text(prompt: str, *, api_key: str, model: str = "gemini-2.5-flash", timeout_s: int = 60) -> str:
    """Call Gemini generateContent and return plain text output."""

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
        },
    }

    r = requests.post(url, headers=headers, json=payload, timeout=timeout_s)
    if r.status_code >= 400:
        raise RuntimeError(f"Gemini HTTP {r.status_code}: {r.text[:300]}")
    data = r.json()

    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        raise RuntimeError(f"Gemini response missing candidate text: {json.dumps(data)[:500]}")


def _parse_gemini_line_format(text: str) -> dict[str, Any]:
    """Parse line-based format from Gemini output.

    Expected:
      RANGE: ...
      ONE_LINER: ...
      POLICY: idx|summary
      RESEARCH: idx|summary
      MARKET: idx|summary
    """

    result: dict[str, Any] = {
        "range": "",
        "one_liner": "",
        "policy": [],
        "research": [],
        "market": [],
    }

    axis_map = {
        "POLICY": "policy",
        "RESEARCH": "research",
        "MARKET": "market",
        "정책": "policy",
        "연구": "research",
        "유통": "market",
    }

    cleaned = text or ""
    # Remove markdown code fences if present
    cleaned = re.sub(r"^```[a-zA-Z0-9_-]*\n", "", cleaned)
    cleaned = re.sub(r"\n```$", "", cleaned)

    for raw in cleaned.splitlines():
        line = raw.strip()
        if not line:
            continue

        # tolerate bullets / markdown emphasis
        line = re.sub(r"^[\-*•]\s*", "", line)
        line = line.replace("**", "")

        m_range = re.match(r"^RANGE\s*:\s*(.+)$", line, flags=re.I)
        if m_range:
            result["range"] = m_range.group(1).strip()
            continue

        m_ol = re.match(r"^ONE_LINER\s*:\s*(.+)$", line, flags=re.I)
        if m_ol:
            result["one_liner"] = m_ol.group(1).strip()
            continue

        m_axis = re.match(r"^(POLICY|RESEARCH|MARKET|정책|연구|유통)\s*:\s*(.+)$", line, flags=re.I)
        if m_axis:
            axis = axis_map[m_axis.group(1).upper() if m_axis.group(1).isascii() else m_axis.group(1)]
            rhs = m_axis.group(2).strip()
            # idx|summary OR idx - summary
            p = rhs.split("|", 1)
            if len(p) != 2:
                p = re.split(r"\s+-\s+", rhs, maxsplit=1)
                if len(p) != 2:
                    continue
            idx_s, summ = p[0].strip(), p[1].strip()
            idx_m = re.search(r"\d+", idx_s)
            if not idx_m:
                continue
            result[axis].append({"idx": int(idx_m.group(0)), "summary": summ})
            continue

    return result


def _korean_fallback_summary(it: RecentItem) -> str:
    ex = (it.excerpt or "").strip()
    title = (it.title or "").strip()

    if ex:
        # Prefer first sentence-like chunk and force short length
        s = re.split(r"(?<=[\.\!\?\u3002\uFF01\uFF1F])\s+", ex)[0].strip()
        if s:
            if len(s) > 140:
                s = s[:139].rstrip() + "…"
            # Non-Korean excerpt: still produce a natural Korean sentence.
            if not re.search(r"[가-힣]", s):
                return f"‘{title}’ 관련 이슈로, 육종·종자 분야의 정책·시장 변화 신호를 다룬다."
            return s

    # If no excerpt, synthesize from title without dead phrases.
    if re.search(r"[가-힣]", title):
        return f"‘{title}’ 관련 핵심 동향으로, 현장 적용과 제도 변화 관점에서 주목할 내용이다."
    return f"‘{title}’ 이슈로, 육종·종자 분야의 최근 변화 방향을 보여준다."


def _is_placeholder_summary(s: str) -> bool:
    t = (s or "").strip().lower()
    if not t:
        return True
    # Common low-quality placeholders
    if re.fullmatch(r"(정책|연구|시장|유통)\s*요약\s*\d*", t):
        return True
    if re.fullmatch(r"summary\s*\d*", t):
        return True
    if "원문 확인" in t and len(t) < 20:
        return True
    return False


def _gemini_korean_summaries_for_items(
    items: list[RecentItem], *, api_key: str, model: str = "gemini-2.5-flash", timeout_s: int = 45
) -> dict[int, str]:
    """Best-effort Korean summaries for fallback-picked items.

    Uses one short request per item for robustness.
    Returns {idx: summary}. Missing idx will be filled by local fallback.
    """

    out: dict[int, str] = {}
    for it in items:
        excerpt = (it.excerpt or "").strip()
        if len(excerpt) > 700:
            excerpt = excerpt[:699] + "…"

        prompt = "\n".join(
            [
                "다음 기사를 한국어로 1문장 요약해라.",
                "조건: 35~95자, 사실 기반, 자리표시자 금지, 불필요한 수식 금지.",
                "출력: 요약문 한 줄만 출력(머리말/번호/따옴표/라벨 금지).",
                f"title: {it.title}",
                f"excerpt: {excerpt or '(본문 발췌 없음)'}",
            ]
        )

        try:
            text = _call_gemini_generate_text(prompt, api_key=api_key, model=model, timeout_s=timeout_s)
        except Exception:
            continue

        line = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
        line = re.sub(r"^[\-*•\d\.\)\s]+", "", line).strip().strip('"“”')
        line = re.sub(r"\s+", " ", line)
        if line and not _is_placeholder_summary(line):
            out[it.idx] = line

    return out


def _fallback_result_from_items(
    items: list[RecentItem], *, range_start: str, range_end: str, api_key: str = "", model: str = "gemini-2.5-flash"
) -> dict[str, Any]:
    # Deterministic fallback: take recent order and split 2 per axis.
    picked = items[:6]
    while len(picked) < 6 and items:
        picked.append(items[len(picked) % len(items)])

    gem_summ: dict[int, str] = {}
    if api_key:
        try:
            gem_summ = _gemini_korean_summaries_for_items(picked, api_key=api_key, model=model)
        except Exception:
            gem_summ = {}

    def pack(chunk: list[RecentItem]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for it in chunk:
            s = gem_summ.get(it.idx) or _korean_fallback_summary(it)
            out.append({"idx": it.idx, "summary": s})
        return out

    return {
        "range": f"{range_start}~{range_end}".strip("~") or "주간",
        "one_liner": "이번 주 핵심 이슈를 정책·연구·현장 관점으로 빠르게 정리했다.",
        "policy": pack(picked[0:2]),
        "research": pack(picked[2:4]),
        "market": pack(picked[4:6]),
    }


def _render_briefing_md(result: dict[str, Any], *, items_by_idx: dict[int, RecentItem]) -> str:
    def render_axis(title: str, key: str) -> list[str]:
        out: list[str] = []
        out.append(f"### {title}\n")
        arr = result.get(key) or []

        # Deduplicate idx while preserving order
        seen_idx: set[int] = set()
        clean_arr: list[dict[str, Any]] = []
        for obj in arr:
            try:
                idx = int(obj.get("idx"))
            except Exception:
                continue
            if idx in seen_idx:
                continue
            seen_idx.add(idx)
            clean_arr.append(obj)

        for obj in clean_arr[:2]:
            idx = int(obj.get("idx"))
            summ = re.sub(r"\s+", " ", (obj.get("summary") or "").strip())
            it = items_by_idx.get(idx)
            if not it:
                continue
            out.append(f"- [{it.title}]({it.item_path}) ([원문]({it.original_url})) — {summ}")

        out.append("")
        return out

    range_str = (result.get("range") or "").strip() or "주간"

    lines: list[str] = []
    lines.append(BRIEFING_START)
    lines.append(f"## 30초 주간 브리핑 ({range_str})\n")

    one_liner = (result.get("one_liner") or "").strip()
    if one_liner and len(one_liner) >= 8:
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
        # 1st attempt
        text = _call_gemini_generate_text(prompt, api_key=api_key, model=model)
        result = _parse_gemini_line_format(text)

        # Basic validation; if sparse/bad format, retry once with strict repair prompt.
        def _axis_len(k: str) -> int:
            return len(result.get(k) or [])

        need_retry = (_axis_len("policy") < 2 or _axis_len("research") < 2 or _axis_len("market") < 2)
        if need_retry:
            repair_prompt = (
                "아래 출력은 형식이 맞지 않다. 설명 없이 라인 포맷으로만 다시 출력하라.\n"
                "RANGE: ...\nONE_LINER: ...\n"
                "POLICY: idx|요약\nPOLICY: idx|요약\n"
                "RESEARCH: idx|요약\nRESEARCH: idx|요약\n"
                "MARKET: idx|요약\nMARKET: idx|요약\n\n"
                f"[원본출력]\n{text}"
            )
            text2 = _call_gemini_generate_text(repair_prompt, api_key=api_key, model=model)
            result2 = _parse_gemini_line_format(text2)
            # Use repaired result if better
            if (
                len(result2.get("policy") or []) >= len(result.get("policy") or [])
                and len(result2.get("research") or []) >= len(result.get("research") or [])
                and len(result2.get("market") or []) >= len(result.get("market") or [])
            ):
                result = result2

        items_by_idx = {it.idx: it for it in items}

        # Final guard: if still incomplete, or picks invalid idx, build deterministic local fallback.
        def _valid_axis_count(axis: str) -> int:
            c = 0
            for obj in (result.get(axis) or []):
                try:
                    idx = int(obj.get("idx"))
                except Exception:
                    continue
                summ = re.sub(r"\s+", " ", (obj.get("summary") or "").strip())
                if idx in items_by_idx and summ and not _is_placeholder_summary(summ):
                    c += 1
            return c

        if (
            _valid_axis_count("policy") < 2
            or _valid_axis_count("research") < 2
            or _valid_axis_count("market") < 2
        ):
            result = _fallback_result_from_items(
                items,
                range_start=range_start,
                range_end=range_end,
                api_key=api_key,
                model=model,
            )

        briefing_md = _render_briefing_md(result, items_by_idx=items_by_idx)
        out_md = insert_briefing_into_index(index_md, briefing_md)
        _write_text(index_path, out_md)
        return {
            "status": "ok",
            "items": len(items),
            "used_fallback": False,
            "counts": {
                "policy": len(result.get("policy") or []),
                "research": len(result.get("research") or []),
                "market": len(result.get("market") or []),
            },
        }
    except Exception as e:
        # API error -> fallback block
        out_md = insert_briefing_into_index(index_md, existing_fallback_block)
        _write_text(index_path, out_md)
        return {"status": "error", "error": str(e), "items": len(items), "used_fallback": bool(existing_fallback_block)}
