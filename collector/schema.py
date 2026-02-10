from __future__ import annotations

from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class PressItem:
    # Standardized schema
    id: str
    source: str
    org: str
    site_id: str
    title: str
    published_at: str  # ISO8601 w/ timezone (KST preferred)
    url: str
    content_text: str = ""
    tags: list[str] = field(default_factory=list)
    attachments: list[dict[str, Any]] = field(default_factory=list)
    fetched_at: str = ""  # ISO8601 w/ timezone
    raw_html: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Keep raw_html only if not None
        if d.get("raw_html") is None:
            d.pop("raw_html", None)
        return d


def iso_now_kst() -> str:
    from zoneinfo import ZoneInfo

    return datetime.now(tz=ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds")
