from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


@dataclass
class HttpConfig:
    user_agent: str = DEFAULT_UA
    timeout_s: float = 20.0
    min_delay_s: float = 0.6
    max_delay_s: float = 1.2
    retries: int = 3
    backoff_factor: float = 0.6


class HttpClient:
    def __init__(self, cfg: Optional[HttpConfig] = None):
        self.cfg = cfg or HttpConfig()
        self.sess = requests.Session()
        retry = Retry(
            total=self.cfg.retries,
            connect=self.cfg.retries,
            read=self.cfg.retries,
            status=self.cfg.retries,
            backoff_factor=self.cfg.backoff_factor,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET", "POST"),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.sess.mount("http://", adapter)
        self.sess.mount("https://", adapter)

    def _sleep_polite(self):
        time.sleep(random.uniform(self.cfg.min_delay_s, self.cfg.max_delay_s))

    def get(self, url: str, *, referer: Optional[str] = None, headers: Optional[dict] = None, **kw):
        self._sleep_polite()
        h = {"User-Agent": self.cfg.user_agent}
        if referer:
            h["Referer"] = referer
        if headers:
            h.update(headers)
        return self.sess.get(url, headers=h, timeout=self.cfg.timeout_s, **kw)

    def post(self, url: str, *, referer: Optional[str] = None, headers: Optional[dict] = None, data=None, **kw):
        self._sleep_polite()
        h = {"User-Agent": self.cfg.user_agent}
        if referer:
            h["Referer"] = referer
        if headers:
            h.update(headers)
        return self.sess.post(url, headers=h, data=data, timeout=self.cfg.timeout_s, **kw)
