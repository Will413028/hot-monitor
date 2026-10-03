import asyncio
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Literal
from urllib.parse import urlsplit
from xml.etree import ElementTree

import httpx
from pydantic import AwareDatetime, BaseModel, ValidationError


class SearchResult(BaseModel):
    title: str
    url: str
    source: str = "hackernews"
    source_id: str
    published_at: AwareDatetime
    score: int = 0
    comment_count: int = 0
    content: str = ""


class SourceStatus(BaseModel):
    source: str
    status: Literal["ok", "partial", "error"]
    count: int = 0
    error: str | None = None


class SearchResponse(BaseModel):
    results: list[SearchResult]
    sources: list[SourceStatus]
    queries: list[str] = []


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data):
        self.parts.append(data)


def plain_text(value: str) -> str:
    parser = PlainText()
    parser.feed(value)
    return " ".join(" ".join(parser.parts).split())


def normalized_url(url: str) -> str | None:
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return None
        return parsed._replace(fragment="").geturl()
    except ValueError:
        return None


class HNHit(BaseModel):
    objectID: str
    title: str | None = None
    url: str | None = None
    created_at: AwareDatetime
    points: int | None = 0
    num_comments: int | None = 0


class SearchUnavailable(Exception):
    pass


async def search_hackernews(query: str, days: int = 7) -> list[SearchResult]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                "https://hn.algolia.com/api/v1/search_by_date",
                params={
                    "query": query,
                    "tags": "story",
                    "hitsPerPage": 20,
                    "numericFilters": f"created_at_i>{int(cutoff.timestamp())}",
                },
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or not isinstance(payload.get("hits"), list):
                raise ValueError("Invalid search response")
    except (httpx.HTTPError, ValueError) as exc:
        raise SearchUnavailable("Hacker News 搜尋暫時無法使用，請稍後重試") from exc

    results: list[SearchResult] = []
    seen: set[str] = set()
    for raw in payload["hits"]:
        try:
            hit = HNHit.model_validate(raw)
        except ValidationError:
            continue
        if not hit.title or not hit.title.strip():
            continue
        url = hit.url or f"https://news.ycombinator.com/item?id={hit.objectID}"
        normalized = normalized_url(url)
        if not normalized:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        results.append(SearchResult(
            title=hit.title.strip(), url=url, source_id=hit.objectID,
            published_at=hit.created_at, score=hit.points or 0,
            comment_count=hit.num_comments or 0,
        ))
    return results


async def search_github_blog(query: str | list[str], days: int = 7) -> list[SearchResult]:
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            response = await client.get("https://github.blog/feed/")
            response.raise_for_status()
            root = ElementTree.fromstring(response.content)
            if root.tag != "rss" or root.find("channel") is None:
                raise ValueError("Invalid RSS feed")
    except (httpx.HTTPError, ElementTree.ParseError, ValueError) as exc:
        raise SearchUnavailable("GitHub Blog RSS 暫時無法使用，請稍後重試") from exc

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    results: list[SearchResult] = []
    for item in root.findall("channel/item"):
        title = plain_text(item.findtext("title", ""))
        content = plain_text(item.findtext("description", ""))
        url = item.findtext("link", "").strip()
        try:
            published = parsedate_to_datetime(item.findtext("pubDate", ""))
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError, IndexError):
            continue
        if not title or not normalized_url(url) or not cutoff <= published <= now:
            continue
        terms = [query] if isinstance(query, str) else query
        if not any(term.casefold() in f"{title} {content}".casefold() for term in terms):
            continue
        results.append(SearchResult(
            title=title, content=content[:1000], url=url, source="github_blog",
            source_id=item.findtext("guid") or url, published_at=published,
        ))
    return results[:20]


async def search_google_news(queries: list[str], days: int = 7) -> list[SearchResult]:
    expression = " OR ".join(f'"{query.replace(chr(34), " ")}"' for query in queries)
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            response = await client.get("https://news.google.com/rss/search", params={
                "q": f"({expression}) when:{days}d", "hl": "en-US", "gl": "US", "ceid": "US:en",
            })
            response.raise_for_status()
            root = ElementTree.fromstring(response.content)
            if root.tag != "rss" or root.find("channel") is None:
                raise ValueError("Invalid RSS feed")
    except (httpx.HTTPError, ElementTree.ParseError, ValueError) as exc:
        raise SearchUnavailable("Google News 搜尋暫時無法使用") from exc
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    results = []
    for item in root.findall("channel/item"):
        title = plain_text(item.findtext("title", ""))
        url = item.findtext("link", "").strip()
        try:
            published = parsedate_to_datetime(item.findtext("pubDate", ""))
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError, IndexError):
            continue
        if not title or not normalized_url(url) or published < cutoff:
            continue
        results.append(SearchResult(title=title, url=url, source="google_news",
                                   source_id=item.findtext("guid") or url, published_at=published,
                                   content=plain_text(item.findtext("description", ""))[:1000]))
    return results[:20]


async def search_all(query: str, days: int = 7, sources: list[str] | None = None) -> SearchResponse:
    return await search_queries([query], days, sources)


async def search_source(source: str, queries: list[str], days: int):
    try:
        if source == "hackernews":
            outcomes = await asyncio.gather(*(search_hackernews(query, days) for query in queries), return_exceptions=True)
            failed = sum(isinstance(outcome, BaseException) for outcome in outcomes)
            if failed == len(queries):
                raise SearchUnavailable("Hacker News unavailable")
            items = [item for outcome in outcomes if not isinstance(outcome, BaseException) for item in outcome]
            return SourceStatus(source=source, status="partial" if failed else "ok", count=len(items),
                                error=f"{failed} 個搜尋詞查詢失敗" if failed else None), items
        items = await (search_github_blog(queries, days) if source == "github_blog" else search_google_news(queries, days))
        return SourceStatus(source=source, status="ok", count=len(items)), items
    except Exception:
        return SourceStatus(source=source, status="error", error=f"{source} 搜尋暫時無法使用"), []


async def search_queries(queries: list[str], days: int = 7, sources: list[str] | None = None) -> SearchResponse:
    sources = list(dict.fromkeys(sources or ["hackernews", "github_blog", "google_news"]))
    outcomes = await asyncio.gather(*(search_source(source, queries, days) for source in sources))
    statuses = []
    results = []
    seen = set()
    for status, items in outcomes:
        statuses.append(status)
        for item in items:
            key = normalized_url(item.url)
            if key and key not in seen:
                seen.add(key)
                results.append(item)
    results.sort(key=lambda item: item.published_at, reverse=True)
    return SearchResponse(results=results, sources=statuses, queries=queries)
