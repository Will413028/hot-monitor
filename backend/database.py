from pathlib import Path
import settings  # Load local environment before choosing the database path.
from datetime import datetime
import os
from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

DB_PATH = Path(os.getenv("HOT_MONITOR_DB", str(Path(__file__).parent / "hot-monitor.db"))).resolve()
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)

@event.listens_for(engine, "connect")
def enable_foreign_keys(connection, _):
    connection.execute("PRAGMA foreign_keys=ON")

class Base(DeclarativeBase):
    pass

class Keyword(Base):
    __tablename__ = "keywords"
    id: Mapped[int] = mapped_column(primary_key=True)
    text: Mapped[str] = mapped_column(String(100), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_check_status: Mapped[str | None] = mapped_column(String(20))


class Hotspot(Base):
    __tablename__ = "hotspots"
    __table_args__ = (UniqueConstraint("keyword_id", "normalized_url"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    keyword_id: Mapped[int] = mapped_column(ForeignKey("keywords.id", ondelete="CASCADE"))
    normalized_url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(30))
    source_id: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    published_at: Mapped[datetime] = mapped_column(DateTime)
    saved_at: Mapped[datetime] = mapped_column(DateTime)
    score: Mapped[int] = mapped_column(default=0)
    comment_count: Mapped[int] = mapped_column(default=0)
    analysis_json: Mapped[str | None] = mapped_column(Text)
    relevance: Mapped[int | None] = mapped_column()
    importance: Mapped[str | None] = mapped_column(String(20))


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = {"sqlite_autoincrement": True}
    id: Mapped[int] = mapped_column(primary_key=True)
    keyword_id: Mapped[int] = mapped_column(ForeignKey("keywords.id", ondelete="CASCADE"), index=True)
    hotspot_id: Mapped[int] = mapped_column(ForeignKey("hotspots.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    email_status: Mapped[str] = mapped_column(String(20), default="disabled")
    email_attempts: Mapped[int] = mapped_column(default=0)
    email_next_at: Mapped[datetime | None] = mapped_column(DateTime)


def get_session():
    with SessionLocal() as session:
        yield session
