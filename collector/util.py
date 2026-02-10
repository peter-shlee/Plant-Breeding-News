from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Optional

from dateutil import parser


def make_id(source: str, site_id: str) -> str:
    raw = f"{source}:{site_id}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def clean_text(s: str) -> str:
    s = re.sub(r"\s+", " ", s or "").strip()
    return s


def parse_date_to_kst_iso(date_str: str) -> Optional[str]:
    """Parse various Korean date formats into ISO8601 with Asia/Seoul tz.

    Accepts formats like:
      - 2026-02-09
      - 2026.02.10
      - 2026-02-09 14:30
    """
    if not date_str:
        return None
    dt = parser.parse(date_str, fuzzy=True)
    # If no tzinfo, localize to KST
    if dt.tzinfo is None:
        from zoneinfo import ZoneInfo

        dt = dt.replace(tzinfo=ZoneInfo("Asia/Seoul"))
    return dt.astimezone(__import__("zoneinfo").ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds")
