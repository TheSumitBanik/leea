from __future__ import annotations
import time
from datetime import datetime, timezone
from typing import Any
import warnings

# Silence SyntaxWarnings from newspaper's regex strings
warnings.filterwarnings("ignore", category=SyntaxWarning, module=r"newspaper(\..*)?$")

from newspaper import Article

from app.utils.config import settings
from app.utils.http import http_client
from app.utils.logger import logger

NEWSAPI_ENDPOINT = "https://newsapi.org/v2/everything"


def _publish_date_to_iso(dt_obj: Any) -> str | None:
    try:
        if hasattr(dt_obj, "isoformat"):
            return dt_obj.isoformat()
        if isinstance(dt_obj, str):
            return dt_obj
    except Exception:
        return None
    return None


def _summarize_article_via_newspaper(url: str, timeout: int = 15) -> dict[str, Any]:
    """
    Fetch and parse article content using newspaper3k for on-ground context.
    Returns dict with title, authors, text (truncated), top_image, publish_date.
    """
    try:
        art = Article(url, language="en")
        art.download()
        art.parse()
        text = (art.text or "").strip()
        if len(text) > 1500:
            text = text[:1500] + "..."
        return {
            "title": getattr(art, "title", None),
            "authors": getattr(art, "authors", []),
            "text": text or None,
            "top_image": getattr(art, "top_image", None),
            "publish_date": _publish_date_to_iso(getattr(art, "publish_date", None)),
        }
    except Exception as e:
        logger.debug(f"newspaper3k failed for {url}: {e}")
        return {"title": None, "authors": [], "text": None, "top_image": None, "publish_date": None}


def fetch_live_news(query_terms: list[str], region_hint: str | None = None, page_size: int = 10) -> dict:
    """
    Query NewsAPI for live headlines matching query_terms and optional region hint.
    For each result, attempt to fetch and parse article text via newspaper3k.
    """
    if not settings.newsapi_key:
        raise RuntimeError("NEWSAPI_KEY not configured in environment")

    q = " ".join(query_terms)
    if region_hint:
        q = f"{q} {region_hint}"

    logger.info(f"Fetching NewsAPI for q='{q}'")
    params = {
        "q": q,
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": page_size,
        "apiKey": settings.newsapi_key,
    }
    data = http_client.get_json(NEWSAPI_ENDPOINT, params=params)
    status = data.get("status")
    if status != "ok":
        raise RuntimeError(f"NewsAPI error: {data}")

    articles = []
    for a in data.get("articles", []):
        url = a.get("url")
        parsed = _summarize_article_via_newspaper(url) if url else {}
        articles.append(
            {
                "source": (a.get("source") or {}).get("name"),
                "author": a.get("author"),
                "title": a.get("title"),
                "description": a.get("description"),
                "url": url,
                "publishedAt": a.get("publishedAt"),
                "content": a.get("content"),
                "parsed": parsed,
            }
        )

    return {
        "queried_at": datetime.now(timezone.utc).isoformat(),
        "query": q,
        "count": len(articles),
        "articles": articles,
    }
