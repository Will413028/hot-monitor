import asyncio
import json
from datetime import timezone

from sqlalchemy import select

from database import Notification, SessionLocal


def notification_data(item):
    return {
        "id": item.id, "keyword_id": item.keyword_id, "hotspot_id": item.hotspot_id,
        "title": item.title, "body": item.body, "is_read": item.is_read,
        "created_at": item.created_at.replace(tzinfo=timezone.utc).isoformat(),
        "email_status": item.email_status,
    }


def read_events(after: int, sessions=SessionLocal):
    with sessions() as session:
        rows = session.scalars(select(Notification).where(Notification.id > after)
                               .order_by(Notification.id).limit(100)).all()
        return [notification_data(row) for row in rows]


async def event_stream(request, after: int, sessions=SessionLocal):
    yield "retry: 3000\n\n"
    idle = 0
    while not await request.is_disconnected():
        rows = await asyncio.to_thread(read_events, after, sessions)
        for row in rows:
            after = row["id"]
            yield f"id: {after}\nevent: notification\ndata: {json.dumps(row, ensure_ascii=False)}\n\n"
        if rows:
            idle = 0
            if len(rows) == 100:
                continue
        else:
            idle += 1
            if idle >= 15:
                yield ": heartbeat\n\n"
                idle = 0
        await asyncio.sleep(1)
