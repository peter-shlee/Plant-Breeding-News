from __future__ import annotations

import re
from typing import Iterable, Optional

from bs4 import BeautifulSoup

from ..schema import iso_now_kst
from ..util import clean_text, make_id, parse_date_to_kst_iso
from .base import BaseSource


class NihhsSource(BaseSource):
    source = "nihhs"
    org = "NIHHS"  # National Institute of Horticultural and Herbal Science

    LIST_URL = "https://www.nihhs.go.kr/usr/nihhs/news_Press_list.do?mc=MN0000000136"
    VIEW_URL = "https://www.nihhs.go.kr/usr/nihhs/news_Press_view.do"

    def iter_list(self, *, since_days: int = 30, max_pages: int = 5) -> Iterable[dict]:
        cutoff = self.cutoff_dt(since_days)
        # NIHHS uses pageIndex in POST form
        for page in range(1, max_pages + 1):
            r = self.http.get(self.LIST_URL, headers={"Accept": "text/html"})
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "lxml")
            rows = soup.select("table tbody tr")
            if not rows:
                break

            for tr in rows:
                tds = tr.find_all("td")
                if len(tds) < 4:
                    continue
                # Title in second column (anchor w/ onclick viewContent('dataNo'))
                a = tr.find("a", onclick=True)
                onclick = a.get("onclick", "") if a else ""
                m = re.search(r"viewContent\('(?P<id>\d+)'\)", onclick)
                if not m:
                    continue
                site_id = m.group("id")
                title = clean_text(a.get_text(" ", strip=True) if a else tds[1].get_text(" ", strip=True))
                date_raw = clean_text(tds[3].get_text(" ", strip=True))
                published_at = parse_date_to_kst_iso(date_raw)
                if not published_at:
                    continue
                # cutoff check
                from dateutil import parser

                if parser.isoparse(published_at) < cutoff:
                    continue

                url = f"{self.VIEW_URL}?dataNo={site_id}&mc=MN0000000136"  # approximate canonical
                yield {
                    "id": make_id(self.source, site_id),
                    "source": self.source,
                    "org": self.org,
                    "site_id": site_id,
                    "title": title,
                    "published_at": published_at,
                    "url": url,
                    "fetched_at": iso_now_kst(),
                }

            # NIHHS list page fetch above always page 1; pagination needs POST.
            # For MVP we stop after first page if max_pages>1 not supported.
            break

    def fetch_detail(self, site_id: str, url: str) -> tuple[str, list[dict], list[str], Optional[str]]:
        # The list page form submits POST to /usr/nihhs/news_Press_view.do with dataNo + mc.
        payload = {"dataNo": site_id, "mc": "MN0000000136"}
        r = self.http.post(self.VIEW_URL, referer=self.LIST_URL, data=payload)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")

        # Content is usually in a div with class 'board_view' or similar.
        content_el = (
            soup.select_one(".view")
            or soup.select_one(".board_view")
            or soup.select_one(".contents")
            or soup.select_one("#contents")
        )
        content_text = clean_text(content_el.get_text(" ", strip=True)) if content_el else ""

        attachments: list[dict] = []
        for a in soup.select("a[href]"):
            href = a.get("href")
            if not href:
                continue
            if any(x in href.lower() for x in ["download", "dwld", "file"]):
                # normalize
                if href.startswith("/"):
                    href = "https://www.nihhs.go.kr" + href
                attachments.append({"title": clean_text(a.get_text(" ", strip=True)) or None, "url": href})
        # de-dupe
        seen = set()
        attachments = [
            a
            for a in attachments
            if not (a.get("url") in seen or seen.add(a.get("url")))
        ]

        tags: list[str] = []
        return content_text, attachments, tags, r.text
