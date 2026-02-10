from __future__ import annotations

import re
from typing import Iterable, Optional

from bs4 import BeautifulSoup

from ..schema import iso_now_kst
from ..util import clean_text, make_id, parse_date_to_kst_iso
from .base import BaseSource


class NicsSource(BaseSource):
    source = "nics"
    org = "NICS"  # National Institute of Crop Science

    LIST_URL = "https://www.nics.go.kr/bbs/list.do?m=100000020&homepageSeCode=nics&bbsId=news"
    BASE = "https://www.nics.go.kr"

    def iter_list(self, *, since_days: int = 30, max_pages: int = 5) -> Iterable[dict]:
        cutoff = self.cutoff_dt(since_days)
        # NICS list seems paginated via pageIndex param in POST; for MVP scrape first page.
        r = self.http.get(self.LIST_URL)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        rows = soup.select("table tbody tr")
        for tr in rows:
            tds = tr.find_all("td")
            if len(tds) < 5:
                continue
            # Title anchor uses onclick bbs.list.view(<id>)
            a = tr.find("a", onclick=True)
            onclick = a.get("onclick", "") if a else ""
            m = re.search(r"bbs\.list\.view\((\d+)\)", onclick)
            if not m:
                continue
            site_id = m.group(1)
            title = clean_text(a.get_text(" ", strip=True) if a else tds[1].get_text(" ", strip=True))
            date_raw = clean_text(tds[-2].get_text(" ", strip=True))
            published_at = parse_date_to_kst_iso(date_raw)
            if not published_at:
                continue
            from dateutil import parser

            if parser.isoparse(published_at) < cutoff:
                continue

            # Attachments are direct download links in the row
            attachments: list[dict] = []
            for fa in tr.select('a[href*="/bbs/file/dwld.do"]'):
                href = fa.get("href")
                if href.startswith("/"):
                    href = self.BASE + href
                attachments.append({"title": None, "url": href})

            # Canonical URL: we don't have a stable view endpoint (direct GET returns error without extra params).
            # For MVP, use list URL with anchor, and store attachments.
            url = self.LIST_URL + f"#ntt-{site_id}"

            yield {
                "id": make_id(self.source, site_id),
                "source": self.source,
                "org": self.org,
                "site_id": site_id,
                "title": title,
                "published_at": published_at,
                "url": url,
                "attachments": attachments,
                "fetched_at": iso_now_kst(),
            }

    def fetch_detail(self, site_id: str, url: str) -> tuple[str, list[dict], list[str], Optional[str]]:
        # No reliable HTML detail page discovered for MVP; rely on attachments from list.
        return "", [], [], None
