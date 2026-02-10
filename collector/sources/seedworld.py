from __future__ import annotations

from typing import Iterable, Optional

from dateutil import parser

from ..rss import html_to_text, parse_feed
from ..schema import iso_now_kst
from ..util import clean_text, make_id, parse_date_to_kst_iso, stable_site_id_from_guid_or_link
from .base import BaseSource


class SeedWorldSource(BaseSource):
    """Seed World RSS feed (summary-only unless expanded later)."""

    source = "seedworld"
    org = "Seed World"

    FEED_URL = "https://www.seedworld.com/feed/"

    def iter_list(self, *, since_days: int = 30, max_pages: int = 5) -> Iterable[dict]:
        # max_pages unused for RSS
        cutoff = self.cutoff_dt(since_days)
        r = self.http.get(self.FEED_URL)
        r.raise_for_status()

        for it in parse_feed(r.text):
            title = clean_text(it.title)
            url = (it.link or "").strip()
            published_at = parse_date_to_kst_iso(it.published)
            if not (title and url and published_at):
                continue
            try:
                if parser.isoparse(published_at) < cutoff:
                    continue
            except Exception:
                pass

            site_id = stable_site_id_from_guid_or_link(it.guid, url)
            content_text = html_to_text(it.description_html)

            yield {
                "id": make_id(self.source, site_id),
                "source": self.source,
                "org": self.org,
                "site_id": site_id,
                "title": title,
                "published_at": published_at,
                "url": url,
                # Use RSS description as content_text (summary-only).
                "content_text": content_text,
                "fetched_at": iso_now_kst(),
            }

    def fetch_detail(self, site_id: str, url: str) -> tuple[str, list[dict], list[str], Optional[str]]:
        # Summary-only by default; list stage already contains cleaned description.
        return "", [], [], None
