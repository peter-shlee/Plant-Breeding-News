from __future__ import annotations

import os
import re
from typing import Iterable, Optional

from .util import clean_text


_TECHNIQUE_TAGS: dict[str, list[str]] = {
    "genomics": [
        "유전체",
        "genome",
        "genomic",
        "genomics",
        "sequencing",
        "resequencing",
        "WGS",
        "RNA-seq",
        "transcriptome",
        "전사체",
    ],
    "marker": [
        "마커",
        "marker",
        "SNP",
        "KASP",
        "SSR",
        "QTL",
        "GWAS",
        "유전자지도",
        "연관분석",
    ],
    "gene-editing": [
        "CRISPR",
        "gene editing",
        "genome editing",
        "유전자편집",
        "유전자가위",
        "TALEN",
    ],
    "phenotyping": [
        "표현체",
        "phenotype",
        "phenotyping",
        "고속표현형",
        "이미징",
        "image analysis",
        "drought",
        "내병성",
        "저항성",
    ],
    "IP-policy": [
        "품종보호",
        "UPOV",
        "variety protection",
        "plant variety protection",
        "PVP",
        "지식재산",
        "지재권",
        "특허",
        "출원",
        "등록",
    ],
}

# Lightweight crop detection keywords -> tag
_CROP_TAGS: dict[str, list[str]] = {
    "벼": ["벼", "쌀", "rice"],
    "밀": ["밀", "wheat"],
    "콩": ["콩", "대두", "soy", "soybean"],
    "감귤": ["감귤", "귤", "citrus", "mandarin"],
    "토마토": ["토마토", "tomato"],
    "고추": ["고추", "pepper", "capsicum"],
    "배추": ["배추", "cabbage", "brassica"],
    "감자": ["감자", "씨감자", "potato", "seed potato"],
    "옥수수": ["옥수수", "maize", "corn"],
}


def auto_tags(*, title: str = "", content_text: str = "", existing: Optional[Iterable[str]] = None) -> list[str]:
    base = " ".join([title or "", content_text or "", " ".join(existing or [])])
    t = _norm(base)

    out: list[str] = []

    for tag, kws in _TECHNIQUE_TAGS.items():
        if _any_hit(t, kws):
            out.append(tag)

    for tag, kws in _CROP_TAGS.items():
        if _any_hit(t, kws):
            out.append(tag)

    # De-dupe, stable order
    return list(dict.fromkeys([*(existing or []), *out]))


def generate_summary(content_text: str, *, max_chars: int = 240) -> str:
    """First 1-2 sentences from cleaned content_text (no LLM)."""
    text = clean_text(content_text or "")
    if not text:
        return ""

    # Remove common boilerplate-ish tails
    text = re.sub(r"(문의\s*[:：].*)$", "", text)

    # Sentence-ish split for Korean/English.
    parts = [p.strip() for p in re.split(r"(?<=[\.!\?\u3002\uFF01\uFF1F])\s+", text) if p.strip()]
    if not parts:
        parts = [text]

    cand = parts[0]
    if len(parts) >= 2 and len(cand) < max_chars * 0.7:
        cand = (cand + " " + parts[1]).strip()

    cand = cand[:max_chars].rstrip()
    # Avoid cutting mid-word for english-ish tokens
    if len(cand) == max_chars and re.search(r"[A-Za-z0-9]$", cand):
        cand = re.sub(r"\s+\S*$", "", cand).rstrip()

    return cand


def attachment_key(url: str, title: Optional[str] = None) -> tuple[str, str]:
    """Return (base, ext) for dedupe grouping."""
    u = url or ""
    name = (title or "").strip()
    name = re.sub(r"\s*\(view\)\s*$", "", name, flags=re.I).strip()

    # Try title first
    ext = _ext_from_name(name) or _ext_from_url(u)

    if name:
        base = re.sub(r"\.[A-Za-z0-9]{1,6}$", "", name)
    else:
        base = os.path.splitext(os.path.basename(u.split("?")[0]))[0]

    base = _norm(base)
    return base or _norm(u.split("?")[0]), (ext or "").lower().lstrip(".")


def is_view_link(url: str) -> bool:
    u = (url or "").lower()
    return any(x in u for x in ["fileview", "view.do", "preview", "openview"]) and not any(
        x in u for x in ["download", "dwld", "filedownload", "filedown", "fileDownLoadDw".lower()]
    )


def _ext_from_url(url: str) -> str:
    path = (url or "").split("?")[0]
    return os.path.splitext(path)[1]


def _ext_from_name(name: str) -> str:
    return os.path.splitext(name or "")[1]


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


def _any_hit(norm_text: str, kws: list[str]) -> bool:
    for kw in kws:
        k = _norm(kw)
        if not k:
            continue
        if re.fullmatch(r"[a-z0-9 ]+", k):
            pat = r"\b" + re.escape(k).replace(r"\ ", r"\s+") + r"\b"
            if re.search(pat, norm_text):
                return True
        else:
            if k in norm_text:
                return True
    return False
