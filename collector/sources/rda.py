from __future__ import annotations

import re
from typing import Iterable, Optional

from bs4 import BeautifulSoup

from ..schema import iso_now_kst
from ..util import clean_text, make_id, parse_date_to_kst_iso
from .base import BaseSource


class RdaSource(BaseSource):
    source = "rda"
    org = "RDA"  # Rural Development Administration

    LIST_URL = "https://www.rda.go.kr/board/board.do?mode=list&prgId=day_farmprmninfoEntry"
    BASE = "https://www.rda.go.kr"

    def iter_list(self, *, since_days: int = 30, max_pages: int = 5) -> Iterable[dict]:
        cutoff = self.cutoff_dt(since_days)
        # RDA uses currPage param
        for page in range(1, max_pages + 1):
            url = self.LIST_URL + f"&currPage={page}"
            r = self.http.get(url)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "lxml")

            # Each item anchor contains dataNo.
            links = soup.select('a[href*="dataNo="]')
            if not links:
                break

            any_yielded = False
            for a in links:
                href = a.get("href")
                if not href or "boardId=farmprmninfo" not in href:
                    continue
                title_el = a.select_one(".c-tit .span")
                title = clean_text(title_el.get_text(" ", strip=True) if title_el else a.get_text(" ", strip=True))
                if not title:
                    continue
                m = re.search(r"dataNo=(\d+)", href)
                if not m:
                    continue
                site_id = m.group(1)
                # date is often in same list item; try to find trailing date within parent
                parent_text = clean_text(a.parent.get_text(" ", strip=True) if a.parent else "")
                date_m = re.search(r"(20\d{2}[-\.]\d{2}[-\.]\d{2})", parent_text)
                published_at = parse_date_to_kst_iso(date_m.group(1)) if date_m else None
                if not published_at:
                    continue
                from dateutil import parser

                if parser.isoparse(published_at) < cutoff:
                    continue

                if href.startswith("/"):
                    full = self.BASE + href
                else:
                    full = href
                any_yielded = True
                yield {
                    "id": make_id(self.source, site_id),
                    "source": self.source,
                    "org": self.org,
                    "site_id": site_id,
                    "title": title,
                    "published_at": published_at,
                    "url": full,
                    "fetched_at": iso_now_kst(),
                }

            if not any_yielded:
                break

    def fetch_detail(self, site_id: str, url: str) -> tuple[str, list[dict], list[str], Optional[str]]:
        r = self.http.get(url, referer=self.LIST_URL)
        r.raise_for_status()
        html = r.text
        soup = BeautifulSoup(html, "lxml")

        # Prefer meta og:description; it usually includes full press text.
        meta = soup.find("meta", attrs={"property": "og:description"})
        content_text = clean_text(meta.get("content", "")) if meta else ""

        # Attachments are buttons calling fn_download(boardId,dataNo,sortNo)
        attachments: list[dict] = []
        for btn in soup.select("#file-list button[onclick]"):
            onclick = btn.get("onclick", "")
            m = re.search(r"fn_download\('(?P<board>[^']+)'\s*,\s*'(?P<data>\d+)'\s*,\s*'?(?P<sort>\d+)'?\)", onclick)
            if not m:
                continue
            board = m.group("board")
            data = m.group("data")
            sort = m.group("sort")
            # Find filename from sibling .name
            li = btn.find_parent("li")
            name = None
            if li:
                name_el = li.select_one(".name")
                name = clean_text(name_el.get_text(" ", strip=True)) if name_el else None
            dl_url = f"{self.BASE}/fileDownLoadDw.do?boardId={board}&dataNo={data}&sortNo={sort}"
            attachments.append({"title": name, "url": dl_url})

        # Also add view URLs if present
        for btn in soup.select("#file-list button[onclick]"):
            onclick = btn.get("onclick", "")
            m = re.search(r"fn_view\('(?P<board>[^']+)'\s*,\s*'(?P<data>\d+)'\s*,\s*'?(?P<sort>\d+)'?\)", onclick)
            if not m:
                continue
            board = m.group("board")
            data = m.group("data")
            sort = m.group("sort")
            li = btn.find_parent("li")
            name = None
            if li:
                name_el = li.select_one(".name")
                name = clean_text(name_el.get_text(" ", strip=True)) if name_el else None
            view_url = f"{self.BASE}/fileViewDw.do?boardId={board}&dataNo={data}&sortNo={sort}"
            attachments.append({"title": (name + " (view)") if name else "view", "url": view_url})

        # de-dupe
        seen = set()
        attachments = [
            a
            for a in attachments
            if a.get("url") and not (a["url"] in seen or seen.add(a["url"]))
        ]

        tags: list[str] = []
        return content_text, attachments, tags, html
