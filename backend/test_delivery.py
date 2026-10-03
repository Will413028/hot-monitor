import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from email.utils import format_datetime
import httpx
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from ai import Analysis, AnalysisResponse, AIUnavailable
from database import Base, Hotspot, Keyword, Notification, get_session, enable_foreign_keys
from email_delivery import EmailDelivery, send_email
from events import event_stream, read_events
from main import app
from monitor import Monitor
from search import SearchResponse, SearchResult, SourceStatus

class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{Path(self.tmp.name) / 'test.db'}", connect_args={'check_same_thread': False})
        event.listen(self.engine, 'connect', enable_foreign_keys)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        with self.sessions() as session:
            keyword = Keyword(text='AI')
            session.add(keyword); session.commit(); self.keyword_id = keyword.id
        def override():
            with self.sessions() as session:
                yield session
        app.dependency_overrides[get_session] = override

    def tearDown(self):
        app.dependency_overrides.clear(); self.engine.dispose(); self.tmp.cleanup()

    def response(self, count=1):
        return SearchResponse(results=[SearchResult(title=f'AI {i}', url=f'https://example.com/{i}', source_id=str(i), published_at=datetime.now(timezone.utc)) for i in range(count)], sources=[SourceStatus(source='hackernews', status='ok')])

    def analysis(self):
        return AnalysisResponse(analysis=Analysis(relevance=90, relevance_reason='直接相關', importance='high', summary='AI 更新摘要'), model='test/model')

    def save(self, count=1):
        async def run():
            with self.sessions() as session, patch('monitor.search_all', AsyncMock(return_value=self.response(count))), patch('monitor.flag', return_value=False):
                await Monitor(self.sessions).check(self.keyword_id, session)
        asyncio.run(run())

    def test_notifications_are_atomic_idempotent_and_readable(self):
        self.save(); self.save()
        with TestClient(app) as client:
            notices = client.get('/notifications').json()
            self.assertEqual(len(notices), 1)
            self.assertEqual(notices[0]['email_status'], 'disabled')
            notice_id = notices[0]['id']
            self.assertTrue(client.patch(f'/notifications/{notice_id}/read').json()['is_read'])
            self.assertEqual(client.get('/notifications?unread_only=true').json(), [])
            client.delete(f'/keywords/{self.keyword_id}')
            self.assertEqual(client.get('/notifications').json(), [])
            self.assertEqual(client.patch(f'/notifications/{notice_id}/read').status_code, 404)

    def test_notification_failure_rolls_back_article_and_check_status(self):
        with self.engine.begin() as connection:
            connection.execute(text("CREATE TRIGGER reject_notice BEFORE INSERT ON notifications BEGIN SELECT RAISE(ABORT, 'test rejection'); END"))
        with self.assertRaises(IntegrityError):
            self.save()
        with self.sessions() as session:
            self.assertEqual(session.scalars(select(Hotspot)).all(), [])
            self.assertEqual(session.scalars(select(Notification)).all(), [])
            self.assertIsNone(session.get(Keyword, self.keyword_id).last_checked_at)
        with self.engine.begin() as connection:
            connection.execute(text('DROP TRIGGER reject_notice'))
        self.save()
        with self.sessions() as session:
            self.assertEqual(len(session.scalars(select(Hotspot)).all()), 1)
            self.assertEqual(len(session.scalars(select(Notification)).all()), 1)

    def test_default_monitor_saves_google_news_and_notifies(self):
        client_class = httpx.AsyncClient
        seen = []
        def handler(request):
            seen.append(request.url.host)
            if request.url.host == 'hn.algolia.com':
                return httpx.Response(200, json={'hits': []})
            if request.url.host == 'github.blog':
                return httpx.Response(200, text='<rss><channel/></rss>')
            self.assertEqual(request.url.host, 'news.google.com')
            date = format_datetime(datetime.now(timezone.utc))
            return httpx.Response(200, text=f'<rss><channel><item><title>AI news</title><link>https://news.google.com/rss/articles/example</link><guid>google1</guid><pubDate>{date}</pubDate></item></channel></rss>')
        with TestClient(app) as client, patch('monitor.flag', return_value=False), patch('search.httpx.AsyncClient', side_effect=lambda **kwargs: client_class(transport=httpx.MockTransport(handler), **kwargs)):
            response = client.post(f'/keywords/{self.keyword_id}/check')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['new_count'], 1)
            self.assertEqual(len(response.json()['sources']), 3)
            self.assertEqual(client.get(f'/keywords/{self.keyword_id}/hotspots').json()[0]['source'], 'google_news')
            self.assertEqual(len(client.get('/notifications').json()), 1)
        self.assertEqual(set(seen), {'hn.algolia.com', 'github.blog', 'news.google.com'})

    def test_failed_ai_attempts_still_consume_budget(self):
        async def run():
            with self.sessions() as session, patch('monitor.flag', side_effect=lambda name: name == 'MONITOR_AI_ENABLED'), patch('monitor.search_all', AsyncMock(return_value=self.response(8))), patch('monitor.analyze_article', AsyncMock(side_effect=AIUnavailable('test failure'))) as ai:
                result = await Monitor(self.sessions).check(self.keyword_id, session)
                self.assertEqual(ai.await_count, 5)
                self.assertEqual(result.ai_error_count, 5)
                self.assertEqual(result.new_count, 8)
        asyncio.run(run())

    def test_saved_analysis_rejects_reused_article_id(self):
        self.save()
        with self.sessions() as session:
            hotspot_id = session.scalar(select(Hotspot.id))
        async def replaced(_):
            with self.sessions() as session:
                session.delete(session.get(Hotspot, hotspot_id)); session.commit()
                now = datetime.now(timezone.utc).replace(tzinfo=None)
                replacement = Hotspot(keyword_id=self.keyword_id, normalized_url='https://example.com/new', title='Different article', url='https://example.com/new', source='hackernews', source_id='new', content='', published_at=now, saved_at=now)
                session.add(replacement); session.commit()
                self.assertEqual(replacement.id, hotspot_id)
            return self.analysis()
        with TestClient(app) as client, patch('main.analyze_article', AsyncMock(side_effect=replaced)):
            self.assertEqual(client.post(f'/hotspots/{hotspot_id}/analyze').status_code, 404)
        with self.sessions() as session:
            self.assertIsNone(session.get(Hotspot, hotspot_id).analysis_json)

    def test_legacy_article_can_queue_email_without_existing_notice(self):
        self.save()
        with self.sessions() as session:
            item_id = session.scalar(select(Hotspot.id))
            for notice in session.scalars(select(Notification)).all():
                session.delete(notice)
            session.commit()
        with TestClient(app) as client, patch('main.analyze_article', AsyncMock(return_value=self.analysis())), patch('main.email_configured', return_value=True):
            self.assertEqual(client.post(f'/hotspots/{item_id}/analyze').status_code, 200)
            notices = client.get('/notifications').json()
            self.assertEqual(len(notices), 1)
            self.assertEqual(notices[0]['email_status'], 'pending')
            self.assertIn('AI 更新摘要', notices[0]['body'])

    def test_sse_replay_cursor_and_monotonic_ids(self):
        self.save(2)
        rows = read_events(0, self.sessions)
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(read_events(rows[0]['id'], self.sessions)), 1)
        class Connected:
            async def is_disconnected(self): return False
        async def run():
            stream = event_stream(Connected(), rows[0]['id'], self.sessions)
            self.assertIn('retry:', await anext(stream))
            frame = await anext(stream)
            self.assertIn(f"id: {rows[1]['id']}", frame)
            self.assertIn('event: notification', frame)
            self.assertIn('data:', frame)
            await stream.aclose()
        asyncio.run(run())
        with self.sessions() as session:
            for notice in session.scalars(select(Notification)).all(): session.delete(notice)
            session.commit()
            item = Notification(keyword_id=self.keyword_id, hotspot_id=1, title='new', body='new', created_at=datetime.now(timezone.utc).replace(tzinfo=None))
            session.add(item); session.commit()
            self.assertGreater(item.id, rows[-1]['id'])

    def test_saved_analysis_filters_and_email_queue(self):
        self.save(2)
        with TestClient(app) as client, patch('main.analyze_article', AsyncMock(return_value=self.analysis())), patch('main.email_configured', return_value=True):
            items = client.get(f'/keywords/{self.keyword_id}/hotspots').json()
            hotspot_id = items[0]['id']
            self.assertEqual(client.post(f'/hotspots/{hotspot_id}/analyze').status_code, 200)
            filtered = client.get(f'/keywords/{self.keyword_id}/hotspots?min_relevance=80&importance=high&sort=relevance').json()
            self.assertEqual(len(filtered), 1)
            self.assertEqual(json.loads(filtered[0]['analysis_json'])['analysis']['summary'], 'AI 更新摘要')
            self.assertEqual(client.get(f'/keywords/{self.keyword_id}/hotspots?source=github_blog').json(), [])
            self.assertEqual(len(client.get(f'/keywords/{self.keyword_id}/hotspots?limit=1&offset=1').json()), 1)
            self.assertEqual(client.get(f'/keywords/{self.keyword_id}/hotspots?sort=invalid').status_code, 422)
            notice = next(item for item in client.get('/notifications').json() if item['hotspot_id'] == hotspot_id)
            self.assertEqual(notice['email_status'], 'pending')
            self.assertFalse(client.patch('/monitor/config', json={'enabled': False}).json()['enabled'])
            self.assertTrue(client.patch('/monitor/config', json={'enabled': True}).json()['enabled'])

    def test_auto_analysis_has_attempt_budget_and_skips_duplicates(self):
        async def run():
            monitor = Monitor(self.sessions)
            with patch('monitor.flag', side_effect=lambda name: name == 'MONITOR_AI_ENABLED'), patch('monitor.search_all', AsyncMock(return_value=self.response(7))), patch('monitor.analyze_article', AsyncMock(return_value=self.analysis())) as ai, patch('monitor.email_configured', return_value=True):
                with self.sessions() as session:
                    result = await monitor.check(self.keyword_id, session)
                    self.assertEqual(result.new_count, 7)
                    self.assertEqual(ai.await_count, 5)
                with self.sessions() as session:
                    await monitor.check(self.keyword_id, session)
                    self.assertEqual(ai.await_count, 5)
                with self.sessions() as session:
                    self.assertEqual(len(session.scalars(select(Notification).where(Notification.email_status == 'pending')).all()), 5)
        asyncio.run(run())

    def test_email_delivery_retries_and_recovers_lease(self):
        self.save()
        with self.sessions() as session:
            item = session.scalar(select(Notification)); item.email_status = 'pending'; session.commit()
        delivery = EmailDelivery(self.sessions)
        with patch('email_delivery.email_configured', return_value=True), patch('email_delivery.send_email', side_effect=OSError('SMTP unavailable')):
            asyncio.run(delivery.deliver())
        with self.sessions() as session:
            item = session.scalar(select(Notification)); self.assertEqual(item.email_status, 'pending'); self.assertEqual(item.email_attempts, 1)
            item.email_next_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1); session.commit()
        with patch('email_delivery.email_configured', return_value=True), patch('email_delivery.send_email') as send:
            asyncio.run(delivery.deliver()); send.assert_called_once()
        with self.sessions() as session:
            item = session.scalar(select(Notification)); self.assertEqual(item.email_status, 'sent')
            item.email_status = 'sending'; item.email_attempts = 3; item.email_next_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1); session.commit()
        with patch('email_delivery.email_configured', return_value=True), patch('email_delivery.send_email') as send:
            asyncio.run(delivery.deliver()); send.assert_not_called()
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(Notification)).email_status, 'failed')

    def test_smtp_tls_and_message(self):
        with patch.dict('os.environ', {'SMTP_HOST': 'test.invalid', 'SMTP_FROM': 'from@example.com', 'SMTP_TO': 'to@example.com', 'SMTP_USERNAME': '', 'SMTP_SSL': 'false', 'SMTP_STARTTLS': 'true'}), patch('email_delivery.smtplib.SMTP') as factory:
            send_email('news', 'body')
            smtp = factory.return_value.__enter__.return_value
            smtp.starttls.assert_called_once()
            smtp.send_message.assert_called_once()
            self.assertEqual(smtp.send_message.call_args.args[0]['To'], 'to@example.com')

if __name__ == '__main__': unittest.main()
