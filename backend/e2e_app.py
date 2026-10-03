"""Isolated deterministic browser-test server. Never use as the application entrypoint."""
import os
if os.getenv("HOT_MONITOR_E2E") != "1":
    raise RuntimeError("This module is only for isolated browser tests")

from datetime import datetime, timezone
import main
import monitor
from database import Base, engine
from ai import Analysis, AnalysisResponse
from search import SearchResponse, SearchResult, SourceStatus

Base.metadata.create_all(engine)

async def fixture_search(query, days=7, sources=None):
    sources = sources or ["hackernews", "github_blog", "google_news"]
    items = [SearchResult(title=f"{query} release", url=f"https://example.com/{source}/release", source=source,
                          source_id=f"{source}-1", published_at=datetime.now(timezone.utc),
                          content=f"Latest {query} features", score=10 if source == "hackernews" else 0)
             for source in sources]
    return SearchResponse(results=items, sources=[SourceStatus(source=source, status="ok", count=1) for source in sources], queries=[query])

async def fixture_queries(queries, days=7, sources=None):
    result = await fixture_search(queries[0], days, sources)
    result.queries = queries
    return result

async def fixture_analysis(payload):
    return AnalysisResponse(analysis=Analysis(relevance=92, relevance_reason="直接討論追蹤主題", importance="high", summary="更新重點摘要"), model="test/fixture")

async def fixture_expand(keyword):
    return [keyword, f"{keyword} alias"]

main.search_all = fixture_search
main.search_queries = fixture_queries
main.analyze_article = fixture_analysis
main.expand_keyword = fixture_expand
monitor.search_all = fixture_search
monitor.search_queries = fixture_queries
monitor.analyze_article = fixture_analysis
monitor.expand_keyword = fixture_expand
app = main.app
