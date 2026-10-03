import asyncio
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import create_engine, select, event
from sqlalchemy.orm import sessionmaker
from database import Base, Hotspot, Keyword, get_session, enable_foreign_keys
from main import app
from monitor import Monitor, MonitorBusy, KeywordMissing
from search import SearchResponse, SearchResult, SourceStatus


def result(status="ok"):
    return SearchResponse(results=[] if status == "error" else [SearchResult(
        title="AI release", url="https://example.com/ai", source_id="1",
        published_at=datetime.now(timezone.utc),
    )], sources=[SourceStatus(source="hackernews", status=status),
                SourceStatus(source="github_blog", status="error" if status != "ok" else "ok")])

class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{Path(self.tmp.name) / 'test.db'}", connect_args={"check_same_thread": False})
        event.listen(self.engine, 'connect', enable_foreign_keys)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        def override():
            with self.sessions() as session:
                yield session
        app.dependency_overrides[get_session] = override

    def tearDown(self):
        app.dependency_overrides.clear()
        self.engine.dispose()
        self.tmp.cleanup()

    def test_deleted_keyword_id_reuse_does_not_save_into_replacement(self):
        with self.sessions() as session:
            keyword = Keyword(text='AI')
            session.add(keyword); session.commit(); keyword_id = keyword.id
        async def replaced(*_):
            with self.sessions() as other:
                other.delete(other.get(Keyword, keyword_id)); other.commit()
                replacement = Keyword(text='Databases')
                other.add(replacement); other.commit()
                self.assertEqual(replacement.id, keyword_id)
            return result()
        async def run():
            with self.sessions() as session, patch('monitor.search_all', AsyncMock(side_effect=replaced)), patch('monitor.flag', return_value=False):
                with self.assertRaises(KeywordMissing):
                    await Monitor(self.sessions).check(keyword_id, session)
        asyncio.run(run())
        with self.sessions() as session:
            self.assertEqual(session.scalars(select(Hotspot)).all(), [])

    def test_saved_results_idempotency_independent_keywords_and_delete(self):
        with TestClient(app) as client, patch('monitor.search_all', AsyncMock(return_value=result())):
            first = client.post('/keywords', json={'text': 'AI'}).json()['id']
            second = client.post('/keywords', json={'text': 'Copilot'}).json()['id']
            self.assertEqual(client.post(f'/keywords/{first}/check').json()['new_count'], 1)
            self.assertEqual(client.post(f'/keywords/{first}/check').json()['new_count'], 0)
            self.assertEqual(client.post(f'/keywords/{second}/check').json()['new_count'], 1)
            saved = client.get(f'/keywords/{first}/hotspots').json()
            self.assertEqual(len(saved), 1)
            self.assertTrue(saved[0]['published_at'].endswith('Z'))
            self.engine.dispose()
            reopened = create_engine(str(self.engine.url))
            with sessionmaker(bind=reopened)() as session:
                self.assertEqual(len(session.scalars(select(Hotspot)).all()), 2)
            reopened.dispose()
            client.delete(f'/keywords/{first}')
            self.assertEqual(client.get(f'/keywords/{first}/hotspots').status_code, 404)
            with self.sessions() as session:
                self.assertEqual(len(session.scalars(select(Hotspot)).all()), 1)
            self.assertEqual(client.post('/keywords/999/check').status_code, 404)
            self.assertEqual(client.get(f'/keywords/{second}/hotspots?limit=101').status_code, 422)
            self.assertEqual(client.get('/monitor/status').json()['interval_seconds'], 300)

    def test_partial_and_total_failure_are_recorded(self):
        with TestClient(app) as client:
            keyword_id = client.post('/keywords', json={'text': 'AI'}).json()['id']
            with patch('monitor.search_all', AsyncMock(return_value=result('partial'))):
                self.assertEqual(client.post(f'/keywords/{keyword_id}/check').json()['status'], 'partial')
            with patch('monitor.search_all', AsyncMock(return_value=result('error'))):
                self.assertEqual(client.post(f'/keywords/{keyword_id}/check').status_code, 502)
            keyword = client.get('/keywords').json()[0]
            self.assertEqual(keyword['last_check_status'], 'error')
            self.assertIsNotNone(keyword['last_checked_at'])
            self.assertEqual(len(client.get(f'/keywords/{keyword_id}/hotspots').json()), 1)

    def test_scheduler_processes_active_only(self):
        with self.sessions() as session:
            session.add_all([Keyword(text='active'), Keyword(text='paused', is_active=False)])
            session.commit()
        async def run():
            monitor = Monitor(self.sessions)
            with patch('monitor.search_all', AsyncMock(return_value=result())) as search:
                await monitor.run_active()
                search.assert_awaited_once_with('active', 7)
                with self.sessions() as session:
                    paused = session.scalar(select(Keyword).where(Keyword.text == 'paused'))
                    self.assertIsNone(await monitor.check(paused.id, session, scheduled=True))
                    self.assertEqual(search.await_count, 1)
                    self.assertEqual((await monitor.check(paused.id, session)).new_count, 1)
        asyncio.run(run())

    def test_timer_runs_monitor_and_saves_results(self):
        with self.sessions() as session:
            session.add(Keyword(text='AI'))
            session.commit()
        async def run():
            completed = asyncio.Event()
            monitor = Monitor(self.sessions)
            async def job():
                await monitor.run_active()
                completed.set()
            scheduler = AsyncIOScheduler()
            scheduler.add_job(job, 'interval', seconds=0.05, max_instances=1)
            with patch('monitor.search_all', AsyncMock(return_value=result())):
                scheduler.start()
                try:
                    await asyncio.wait_for(completed.wait(), timeout=3)
                    with self.sessions() as session:
                        self.assertEqual(len(session.scalars(select(Hotspot)).all()), 1)
                        self.assertEqual(session.scalar(select(Keyword)).last_check_status, 'ok')
                finally:
                    scheduler.shutdown(wait=False)
        asyncio.run(run())

    def test_overlapping_check_rejected(self):
        with self.sessions() as session:
            keyword = Keyword(text='AI')
            session.add(keyword)
            session.commit()
            keyword_id = keyword.id
        async def run():
            monitor = Monitor(self.sessions)
            entered = asyncio.Event()
            release = asyncio.Event()
            async def slow_search(*args):
                entered.set()
                await release.wait()
                return result()
            with patch('monitor.search_all', slow_search):
                with self.sessions() as first, self.sessions() as second:
                    task = asyncio.create_task(monitor.check(keyword_id, first))
                    await entered.wait()
                    with self.assertRaises(MonitorBusy):
                        await monitor.check(keyword_id, second)
                    release.set()
                    await task
        asyncio.run(run())

if __name__ == '__main__':
    unittest.main()
