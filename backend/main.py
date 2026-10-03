from typing import Annotated
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from datetime import timedelta
from typing import Literal
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from database import Hotspot, Keyword, Notification, get_session
from settings import email_configured, flag, interval_seconds
from email_delivery import EmailDelivery
from events import event_stream, notification_data
from monitor import CheckResponse, KeywordMissing, Monitor, MonitorBusy
from search import SearchResult, SearchResponse, SearchUnavailable, search_hackernews, search_all, search_queries
from ai import AnalysisRequest, AnalysisResponse, AIUnavailable, AINotConfigured, analyze_article, expand_keyword

@asynccontextmanager
async def lifespan(app):
    app.state.monitor = Monitor()
    app.state.email = EmailDelivery()
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(app.state.monitor.run_active, "interval", seconds=interval_seconds(),
                      id="monitor", max_instances=1, coalesce=True)
    scheduler.add_job(app.state.email.deliver, "interval", seconds=30,
                      id="email", max_instances=1, coalesce=True)
    app.state.scheduler = scheduler
    scheduler.start()
    if not flag("MONITOR_ENABLED", True):
        scheduler.pause_job("monitor")
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)

app = FastAPI(title="Hot Monitor API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(","),
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
)
SessionDep = Annotated[Session, Depends(get_session)]

class HealthResponse(BaseModel):
    status: str
    service: str

class KeywordCreate(BaseModel):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]

class KeywordUpdate(BaseModel):
    is_active: bool

class KeywordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    text: str
    is_active: bool
    last_checked_at: datetime | None
    last_check_status: str | None

    @field_validator("last_checked_at")
    @classmethod
    def utc_timestamp(cls, value):
        return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value

class HotspotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    keyword_id: int
    title: str
    url: str
    source: str
    content: str
    published_at: datetime
    saved_at: datetime
    score: int
    comment_count: int
    relevance: int | None
    importance: str | None
    analysis_json: str | None

@app.get("/monitor/status")
def monitor_status(request: Request):
    job = request.app.state.scheduler.get_job("monitor")
    return {"enabled": job is not None and job.next_run_time is not None, "interval_seconds": interval_seconds(),
            "running": request.app.state.monitor.lock.locked(),
            "next_run_at": job.next_run_time if job else None,
            "ai_enabled": flag("MONITOR_AI_ENABLED"), "email_enabled": email_configured()}

class MonitorConfig(BaseModel):
    enabled: bool

@app.patch("/monitor/config")
def monitor_config(payload: MonitorConfig, request: Request):
    if payload.enabled:
        request.app.state.scheduler.resume_job("monitor")
    else:
        request.app.state.scheduler.pause_job("monitor")
    return monitor_status(request)

@app.post("/keywords/{keyword_id}/check", response_model=CheckResponse)
async def check_keyword(keyword_id: int, request: Request, session: SessionDep):
    try:
        result = await request.app.state.monitor.check(keyword_id, session)
    except KeywordMissing:
        raise HTTPException(404, "找不到关键词")
    except MonitorBusy:
        raise HTTPException(409, "已有監控工作執行中，請稍後重試")
    if result.status == "error":
        raise HTTPException(502, result.model_dump(mode="json"))
    return result

@app.get("/keywords/{keyword_id}/hotspots", response_model=list[HotspotResponse])
def saved_hotspots(keyword_id: int, session: SessionDep,
                   limit: Annotated[int, Query(ge=1, le=100)] = 50,
                   offset: Annotated[int, Query(ge=0)] = 0,
                   source: Literal["hackernews", "github_blog", "google_news"] | None = None,
                   importance: Literal["low", "medium", "high", "urgent"] | None = None,
                   min_relevance: Annotated[int, Query(ge=0, le=100)] | None = None,
                   days: Annotated[int, Query(ge=1, le=365)] | None = None,
                   sort: Literal["time", "relevance", "score"] = "time"):
    if session.get(Keyword, keyword_id) is None:
        raise HTTPException(404, "找不到关键词")
    statement = select(Hotspot).where(Hotspot.keyword_id == keyword_id)
    if source:
        statement = statement.where(Hotspot.source == source)
    if importance:
        statement = statement.where(Hotspot.importance == importance)
    if min_relevance is not None:
        statement = statement.where(Hotspot.relevance >= min_relevance)
    if days:
        statement = statement.where(Hotspot.published_at >= datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days))
    order = {"time": Hotspot.published_at, "relevance": Hotspot.relevance, "score": Hotspot.score}[sort]
    items = session.scalars(statement.order_by(order.desc(), Hotspot.id.desc()).limit(limit).offset(offset)).all()
    # SQLite stores UTC timestamps without timezone information.
    return [HotspotResponse.model_validate(item).model_copy(update={
        "published_at": item.published_at.replace(tzinfo=timezone.utc),
        "saved_at": item.saved_at.replace(tzinfo=timezone.utc),
    }) for item in items]

@app.post("/hotspots/{hotspot_id}/analyze", response_model=AnalysisResponse)
async def analyze_saved(hotspot_id: int, session: SessionDep):
    item = session.get(Hotspot, hotspot_id)
    if item is None:
        raise HTTPException(404, "找不到文章")
    identity = (item.keyword_id, item.normalized_url, item.saved_at)
    keyword = session.get(Keyword, item.keyword_id)
    if keyword is None:
        raise HTTPException(404, "文章已刪除")
    try:
        result = await analyze_article(AnalysisRequest(keyword=keyword.text, title=item.title[:500], content=item.content[:2000]))
    except AINotConfigured as exc:
        raise HTTPException(503, str(exc)) from exc
    except AIUnavailable as exc:
        raise HTTPException(502, str(exc)) from exc
    session.expire_all()
    item = session.get(Hotspot, hotspot_id)
    if item is None or (item.keyword_id, item.normalized_url, item.saved_at) != identity:
        raise HTTPException(404, "文章已刪除")
    item.analysis_json = result.model_dump_json()
    item.relevance = result.analysis.relevance
    item.importance = result.analysis.importance
    if result.analysis.importance in {"high", "urgent"} and email_configured():
        notice = session.scalar(select(Notification).where(Notification.hotspot_id == hotspot_id))
        if notice is None:
            session.add(Notification(keyword_id=item.keyword_id, hotspot_id=item.id,
                                     title=f"{keyword.text}：{item.title}",
                                     body=f"{result.analysis.summary}\n{item.url}",
                                     created_at=datetime.now(timezone.utc).replace(tzinfo=None),
                                     email_status="pending"))
        elif notice.email_status == "disabled":
            notice.email_status = "pending"
            notice.body = f"{result.analysis.summary}\n{item.url}"
    session.commit()
    return result

@app.get("/notifications")
def notifications(session: SessionDep, limit: Annotated[int, Query(ge=1, le=100)] = 50,
                  unread_only: bool = False):
    statement = select(Notification)
    if unread_only:
        statement = statement.where(Notification.is_read.is_(False))
    return [notification_data(item) for item in session.scalars(statement.order_by(Notification.id.desc()).limit(limit))]

@app.patch("/notifications/{notification_id}/read")
def read_notification(notification_id: int, session: SessionDep):
    item = session.get(Notification, notification_id)
    if item is None:
        raise HTTPException(404, "找不到通知")
    item.is_read = True
    session.commit()
    return notification_data(item)

@app.get("/events")
async def events(request: Request, after: Annotated[int, Query(ge=0)] = 0):
    last_id = request.headers.get("last-event-id")
    if last_id is not None:
        try:
            after = max(after, int(last_id))
        except ValueError:
            raise HTTPException(422, "事件 ID 格式錯誤")
    return StreamingResponse(event_stream(request, after), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@app.get("/health", response_model=HealthResponse)
def health():
    return HealthResponse(status="ok", service="hot-monitor-api")

@app.post("/analyze", response_model=AnalysisResponse)
async def analyze(payload: AnalysisRequest):
    try:
        return await analyze_article(payload)
    except AINotConfigured as exc:
        raise HTTPException(503, str(exc)) from exc
    except AIUnavailable as exc:
        raise HTTPException(502, str(exc)) from exc

@app.get("/search", response_model=list[SearchResult])
async def search(
    q: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)],
    days: Annotated[int, Query(ge=1, le=30)] = 7,
):
    try:
        return await search_hackernews(q, days)
    except SearchUnavailable as exc:
        raise HTTPException(502, str(exc)) from exc

@app.get("/search/all", response_model=SearchResponse)
async def aggregate_search(
    q: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)],
    days: Annotated[int, Query(ge=1, le=30)] = 7,
    sources: Annotated[list[Literal["hackernews", "github_blog", "google_news"]], Query()] = ["hackernews", "github_blog"],
):
    response = await search_all(q, days, sources)
    if all(source.status == "error" for source in response.sources):
        raise HTTPException(502, response.model_dump(mode="json"))
    return response

@app.get("/search/expanded", response_model=SearchResponse)
async def expanded_search(
    q: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)],
    days: Annotated[int, Query(ge=1, le=30)] = 7,
    sources: Annotated[list[Literal["hackernews", "github_blog", "google_news"]], Query()] = ["hackernews", "github_blog"],
):
    try:
        queries = await expand_keyword(q)
    except AINotConfigured as exc:
        raise HTTPException(503, str(exc)) from exc
    except AIUnavailable as exc:
        raise HTTPException(502, str(exc)) from exc
    response = await search_queries(queries, days, sources)
    if all(source.status == "error" for source in response.sources):
        raise HTTPException(502, response.model_dump(mode="json"))
    return response

@app.get("/keywords", response_model=list[KeywordResponse])
def list_keywords(session: SessionDep):
    return session.scalars(select(Keyword).order_by(Keyword.id.desc())).all()

@app.post("/keywords", response_model=KeywordResponse, status_code=201)
def create_keyword(payload: KeywordCreate, session: SessionDep):
    keyword = Keyword(text=payload.text)
    session.add(keyword)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, "此關鍵字已存在")
    session.refresh(keyword)
    return keyword

@app.patch("/keywords/{keyword_id}", response_model=KeywordResponse)
def update_keyword(keyword_id: int, payload: KeywordUpdate, session: SessionDep):
    keyword = session.get(Keyword, keyword_id)
    if keyword is None:
        raise HTTPException(404, "找不到关键词")
    keyword.is_active = payload.is_active
    session.commit()
    session.refresh(keyword)
    return keyword

@app.delete("/keywords/{keyword_id}", status_code=204)
def delete_keyword(keyword_id: int, session: SessionDep):
    keyword = session.get(Keyword, keyword_id)
    if keyword is None:
        raise HTTPException(404, "找不到关键词")
    session.delete(keyword)
    session.commit()
    return Response(status_code=204)
