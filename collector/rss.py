from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Optional

from bs4 import BeautifulSoup

from .util import clean_text


@dataclass(frozen=True)
class RssItem:
    title: str
    link: str
    guid: str
    published: str
    description_html: str


def html_to_text(s: str) -> str:
    """Convert RSS description/content:encoded HTML into plain-ish text."""
    if not s:
        return ""
    s = html.unescape(s)
    # Some feeds embed html inside CDATA; keep basic spacing
    soup = BeautifulSoup(s, "lxml")
    # Drop script/style
    for el in soup.select("script,style"):
        el.decompose()
    text = soup.get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip()
    return clean_text(text)


def _text(el: Optional[ET.Element]) -> str:
    if el is None or el.text is None:
        return ""
    return el.text.strip()


def _find_first_text(item: ET.Element, paths: list[str], ns: dict[str, str]) -> str:
    for p in paths:
        el = item.find(p, ns)
        v = _text(el)
        if v:
            return v
    return ""


def parse_feed(xml_text: str) -> list[RssItem]:
    """Parse RSS 2.0 or Atom feeds into a list of RssItem.

    We keep raw description HTML so callers can decide how to use it.
    """
    if not xml_text:
        return []

    try:
        root = ET.fromstring(xml_text)
    except Exception:
        # Some feeds have leading BOM/garbage
        xml_text = xml_text.lstrip("\ufeff\ufffe\ufeff")
        root = ET.fromstring(xml_text)

    # namespace map (best-effort)
    ns = {
        "content": "http://purl.org/rss/1.0/modules/content/",
        "atom": "http://www.w3.org/2005/Atom",
    }

    items: list[RssItem] = []

    # RSS 2.0: <rss><channel><item>
    rss_items = root.findall("./channel/item")
    if rss_items:
        for it in rss_items:
            title = _find_first_text(it, ["title"], ns)
            link = _find_first_text(it, ["link"], ns)
            guid = _find_first_text(it, ["guid"], ns)
            pub = _find_first_text(it, ["pubDate", "date"], ns)
            desc = _find_first_text(it, ["description", "content:encoded"], ns)
            items.append(RssItem(title=title, link=link, guid=guid, published=pub, description_html=desc))
        return items

    # Atom: <feed><entry>
    atom_entries = root.findall("{http://www.w3.org/2005/Atom}entry") or root.findall("./atom:entry", ns)
    for e in atom_entries:
        title = _find_first_text(e, ["atom:title", "title"], ns)

        # link: <link href="..."/>
        link = ""
        link_el = e.find("atom:link[@rel='alternate']", ns) or e.find("atom:link", ns) or e.find("link")
        if link_el is not None:
            link = (link_el.attrib.get("href") or "").strip() or _text(link_el)

        guid = _find_first_text(e, ["atom:id", "id"], ns)
        pub = _find_first_text(e, ["atom:updated", "atom:published", "updated", "published"], ns)

        # content/summary can be HTML
        desc_el = e.find("atom:summary", ns) or e.find("atom:content", ns) or e.find("summary") or e.find("content")
        desc = ""
        if desc_el is not None:
            desc = (desc_el.text or "").strip()
        items.append(RssItem(title=title, link=link, guid=guid, published=pub, description_html=desc))

    return items
