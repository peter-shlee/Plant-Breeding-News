from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Optional

from dateutil import parser


def make_id(source: str, site_id: str) -> str:
    raw = f"{source}:{site_id}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def stable_site_id_from_guid_or_link(guid: str | None, link: str | None) -> str:
    """Create a stable site_id for RSS-like sources.

    Preference order:
    1) guid (if present)
    2) sha1(link)

    We avoid using full URLs as site_id to keep paths short and filesystem-safe.
    """

    g = (guid or "").strip()
    if g:
        return g

    u = (link or "").strip()
    if not u:
        return hashlib.sha1(b"missing-link").hexdigest()

    return hashlib.sha1(u.encode("utf-8")).hexdigest()


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
    tzinfos = {
        # common US abbreviations in RSS feeds
        "UTC": 0,
        "GMT": 0,
        "EST": -5 * 3600,
        "EDT": -4 * 3600,
        "CST": -6 * 3600,
        "CDT": -5 * 3600,
        "MST": -7 * 3600,
        "MDT": -6 * 3600,
        "PST": -8 * 3600,
        "PDT": -7 * 3600,
    }
    dt = parser.parse(date_str, fuzzy=True, tzinfos=tzinfos)
    # If no tzinfo, localize to KST
    if dt.tzinfo is None:
        from zoneinfo import ZoneInfo

        dt = dt.replace(tzinfo=ZoneInfo("Asia/Seoul"))
    return dt.astimezone(__import__("zoneinfo").ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds")
