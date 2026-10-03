import asyncio
import logging
from datetime import datetime, timezone

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert

from database import Hotspot, Keyword, Notification, SessionLocal
from search import SourceStatus, normalized_url, search_all, search_queries
from ai import AnalysisRequest, analyze_article, expand_keyword, AINotConfigured, AIUnavailable
from settings import email_configured, flag

logger = logging.getLogger(__name__)


class MonitorBusy(Exception):
    pass


class KeywordMissing(Exception):
    pass


class CheckResponse(BaseModel):
    keyword_id: int
    new_count: int
    status: str
    sources: list[SourceStatus]
    ai_error_count: int = 0


class Monitor:
    def __init__(self, sessions=SessionLocal):
        self.sessions = sessions
        self.lock = asyncio.Lock()

    async def check(self, keyword_id, session, scheduled=False):
        if self.lock.locked():
            raise MonitorBusy()
        async with self.lock:
            keyword = session.get(Keyword, keyword_id)
            if keyword is None:
                raise KeywordMissing()
            if scheduled and not keyword.is_active:
                return None
            text = keyword.text
            ai_errors = 0
            if flag("MONITOR_EXPANSION_ENABLED"):
                try:
                    response = await search_queries(await expand_keyword(text), 7)
                except (AINotConfigured, AIUnavailable):
                    ai_errors += 1
                    response = await search_all(text, 7)
            else:
                response = await search_all(text, 7)
            existing_urls = set(session.scalars(select(Hotspot.normalized_url).where(Hotspot.keyword_id == keyword_id)))
            analyzed = {}
            attempts = 0
            if flag("MONITOR_AI_ENABLED"):
                for item in response.results:
                    key = normalized_url(item.url)
                    if key in existing_urls or attempts >= 5:
                        continue
                    attempts += 1
                    try:
                        analyzed[key] = await analyze_article(AnalysisRequest(keyword=text, title=item.title[:500], content=item.content[:2000]))
                    except (AINotConfigured, AIUnavailable):
                        ai_errors += 1
            session.expire_all()
            keyword = session.get(Keyword, keyword_id)
            if keyword is None or keyword.text != text:
                raise KeywordMissing()
            if scheduled and not keyword.is_active:
                return None
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            successful = [source for source in response.sources if source.status != "error"]
            status = "error" if not successful else "ok" if all(source.status == "ok" for source in response.sources) else "partial"
            new_count = 0
            for item in response.results:
                analysis = analyzed.get(normalized_url(item.url))
                statement = insert(Hotspot).values(
                    keyword_id=keyword_id, normalized_url=normalized_url(item.url),
                    title=item.title, url=item.url, source=item.source, source_id=item.source_id,
                    content=item.content, published_at=item.published_at.astimezone(timezone.utc).replace(tzinfo=None),
                    saved_at=now, score=item.score, comment_count=item.comment_count,
                    analysis_json=analysis.model_dump_json() if analysis else None,
                    relevance=analysis.analysis.relevance if analysis else None,
                    importance=analysis.analysis.importance if analysis else None,
                ).on_conflict_do_nothing(index_elements=["keyword_id", "normalized_url"]).returning(Hotspot.id)
                hotspot_id = session.execute(statement).scalar_one_or_none()
                if hotspot_id is not None:
                    new_count += 1
                    summary = analysis.analysis.summary if analysis else item.title
                    important = analysis is not None and analysis.analysis.importance in {"high", "urgent"}
                    session.add(Notification(
                        keyword_id=keyword_id, hotspot_id=hotspot_id,
                        title=f"{text}：{item.title}", body=f"{summary}\n{item.url}", created_at=now,
                        email_status="pending" if important and email_configured() else "disabled",
                    ))
            keyword.last_checked_at = now
            keyword.last_check_status = status
            session.commit()
            return CheckResponse(keyword_id=keyword_id, new_count=new_count, status=status, sources=response.sources, ai_error_count=ai_errors)

    async def run_active(self):
        with self.sessions() as session:
            ids = list(session.scalars(select(Keyword.id).where(Keyword.is_active.is_(True))))
        for keyword_id in ids:
            try:
                with self.sessions() as session:
                    await self.check(keyword_id, session, scheduled=True)
            except MonitorBusy:
                continue
            except KeywordMissing:
                continue
            except Exception:
                logger.error("Keyword monitoring failed for id=%s", keyword_id)
