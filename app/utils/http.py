from __future__ import annotations
from typing import Any, Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import feedparser
from app.utils.logger import logger
from .config import settings


class HttpClient:
    def __init__(self, timeout: int | None = None, retries: int | None = None):
        self.timeout = timeout or settings.http_timeout
        self.retries = retries or settings.http_retries
        self.session = requests.Session()
        retry = Retry(
            total=self.retries,
            read=self.retries,
            connect=self.retries,
            backoff_factor=0.8,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET", "HEAD"),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        self.session.headers.update({
            "User-Agent": "LEEA/1.0 (+https://example.com)"
        })

    def _mask_params(self, params: Optional[dict[str, Any]]) -> dict[str, Any]:
        if not params:
            return {}
        masked = dict(params)
        for k in list(masked.keys()):
            if k.lower() in ("apikey", "api_key", "key", "token"):
                masked[k] = "***"
        return masked

    def get_json(self, url: str, params: Optional[dict[str, Any]] = None, headers: Optional[dict[str, str]] = None) -> Any:
        safe_params = self._mask_params(params)
        resp = self.session.get(url, params=params, headers=headers, timeout=self.timeout)
        preview = resp.text[:2000] if resp and resp.text else ""
        logger.info(
            "HTTP JSON GET {url} status={status} params={params} preview={preview}",
            url=url,
            status=getattr(resp, "status_code", None),
            params=safe_params,
            preview=preview,
        )
        resp.raise_for_status()
        return resp.json()

    def get_text(self, url: str, params: Optional[dict[str, Any]] = None, headers: Optional[dict[str, str]] = None) -> str:
        safe_params = self._mask_params(params)
        resp = self.session.get(url, params=params, headers=headers, timeout=self.timeout)
        preview = resp.text[:2000] if resp and resp.text else ""
        logger.info(
            "HTTP TEXT GET {url} status={status} params={params} preview={preview}",
            url=url,
            status=getattr(resp, "status_code", None),
            params=safe_params,
            preview=preview,
        )
        resp.raise_for_status()
        return resp.text

    def get_feed(self, url: str) -> feedparser.FeedParserDict:
        logger.info("HTTP FEED GET {url}", url=url)
        text = self.get_text(url)
        feed = feedparser.parse(text)
        logger.info("Parsed feed {url} entries={n}", url=url, n=len(feed.entries) if getattr(feed, "entries", None) is not None else 0)
        return feed


http_client = HttpClient()
