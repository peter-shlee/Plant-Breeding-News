from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Iterable, Optional

from ..http import HttpClient
from ..schema import PressItem


class BaseSource(ABC):
    source: str
    org: str

    def __init__(self, http: HttpClient):
        self.http = http

    @abstractmethod
    def iter_list(self, *, since_days: int = 30, max_pages: int = 5) -> Iterable[dict]:
        """Yield dicts with minimally: site_id, title, published_at (iso), url, attachments(optional)."""

    @abstractmethod
    def fetch_detail(self, site_id: str, url: str) -> tuple[str, list[dict], list[str], Optional[str]]:
        """Return (content_text, attachments, tags, raw_html)."""

    def cutoff_dt(self, since_days: int) -> datetime:
        from zoneinfo import ZoneInfo

        return datetime.now(tz=ZoneInfo("Asia/Seoul")) - timedelta(days=since_days)
