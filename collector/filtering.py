from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


@dataclass(frozen=True)
class FilterDecision:
    keep: bool
    reason: str
    exclude_hits: tuple[str, ...] = ()
    include_hits: tuple[str, ...] = ()


# Conservative animal/livestock/pet exclusion.
# Philosophy:
# - Do NOT require plant keywords (to avoid dropping seed/policy items).
# - If animal keywords appear but plant keywords also appear, keep (assume mixed/plant context).
# - Use whole-word-ish matching for English where possible.

_EXCLUDE_KEYWORDS_KO = [
    # livestock industry
    "축산",
    "한우",
    "젖소",
    "소고기",
    "돼지",
    "양돈",
    "우유",
    "낙농",
    "가금",
    "닭",
    "계란",
    "양계",
    "오리",
    "사료",
    "가축",
    "축종",
    "분뇨",
    # pets
    "반려",
    "반려견",
    "반려묘",
    # veterinary / animal disease
    "수의",
    "구제역",
    "조류인플루엔자",
    # reproduction/breeding (animal context)
    "정액",
    # other animal production
    "양봉",
    "누에",
]

_EXCLUDE_KEYWORDS_EN = [
    "livestock",
    "cattle",
    "beef",
    "dairy",
    "milk",
    "pork",
    "pig",
    "swine",
    "poultry",
    "chicken",
    "duck",
    "egg",
    "pet",
    "pets",
    "companion animal",
    "animal feed",
    "feed",
    "manure",
    "veterinary",
    "bee",
    "beekeeping",
    "sericulture",
    "silkworm",
]

# Light plant/seed "include" signals to reduce false positives when animal terms are incidental
# (e.g., "사료용 옥수수" should stay).
_INCLUDE_KEYWORDS_KO = [
    "종자",
    "씨앗",
    "품종",
    "육종",
    "작물",
    "원예",
    "과수",
    "채소",
    "벼",
    "쌀",
    "밀",
    "보리",
    "콩",
    "감귤",
    "토마토",
    "고추",
    "배추",
    "감자",
    "씨감자",
    "옥수수",
    "식물",
]

_INCLUDE_KEYWORDS_EN = [
    "seed",
    "seeds",
    "variety",
    "cultivar",
    "breeding",
    "plant",
    "crop",
    "horticulture",
    "rice",
    "wheat",
    "barley",
    "soy",
    "soybean",
    "potato",
    "tomato",
    "pepper",
    "cabbage",
    "citrus",
    "maize",
    "corn",
]


def _find_hits(text: str, keywords: Iterable[str]) -> list[str]:
    t = _norm(text)
    hits: list[str] = []
    for kw in keywords:
        k = _norm(kw)
        if not k:
            continue
        # English keywords: attempt word boundary matching when it looks like a word.
        if re.fullmatch(r"[a-z0-9 ]+", k):
            # Convert spaces to \s+ to match variants.
            pat = r"\\b" + re.escape(k).replace(r"\\ ", r"\\s+") + r"\\b"
            if re.search(pat, t):
                hits.append(kw)
        else:
            if k in t:
                hits.append(kw)
    return hits


def decide_plant_only(*, title: str = "", content_text: str = "", tags: Optional[list[str]] = None) -> FilterDecision:
    """Default filter: keep everything except clearly animal/livestock/pet-related items.

    If exclude keywords are present but plant keywords are also present, we KEEP to avoid
    dropping seed/crop policy items.

    Notes/caveats:
    - "양봉" and "누에" are treated as animal-related by default (they are not plants).
      If you want to include apiculture/sericulture, remove them from the exclude list.
    - "정액" is treated as animal-related; may appear in unrelated contexts, but rare.
    """

    text = " ".join(
        [
            title or "",
            content_text or "",
            " ".join(tags or []),
        ]
    )

    exclude_hits = _find_hits(text, _EXCLUDE_KEYWORDS_KO) + _find_hits(text, _EXCLUDE_KEYWORDS_EN)
    if not exclude_hits:
        return FilterDecision(keep=True, reason="no_exclude_hits")

    include_hits = _find_hits(text, _INCLUDE_KEYWORDS_KO) + _find_hits(text, _INCLUDE_KEYWORDS_EN)
    if include_hits:
        return FilterDecision(
            keep=True,
            reason="exclude_hits_but_plant_signals_present",
            exclude_hits=tuple(dict.fromkeys(exclude_hits)),
            include_hits=tuple(dict.fromkeys(include_hits)),
        )

    return FilterDecision(
        keep=False,
        reason="animal_related",
        exclude_hits=tuple(dict.fromkeys(exclude_hits)),
        include_hits=(),
    )
