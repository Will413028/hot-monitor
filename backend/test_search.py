import unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from unittest.mock import patch
import httpx
from fastapi.testclient import TestClient
from main import app

class SearchTests(unittest.TestCase):
    def run_search(self, handler, params=None):
        client_class = httpx.AsyncClient
        transport = httpx.MockTransport(handler)
        with patch('search.httpx.AsyncClient', side_effect=lambda **kwargs: client_class(transport=transport, **kwargs)):
            with TestClient(app) as client:
                return client.get('/search', params=params or {'q': 'Claude', 'days': 7})

    def test_mapping_dedup_and_safe_links(self):
        def handler(request):
            self.assertEqual(request.url.params['query'], 'Claude')
            self.assertEqual(request.url.params['tags'], 'story')
            self.assertTrue(request.url.params['numericFilters'].startswith('created_at_i>'))
            base = {'title': 'Claude release', 'created_at': '2026-10-01T00:00:00Z', 'points': 5, 'num_comments': 2}
            return httpx.Response(200, json={'hits': [
                dict(base, objectID='1', url='https://example.com/article#first'),
                dict(base, objectID='2', url='https://example.com/article#second'),
                dict(base, objectID='3', url=None),
                dict(base, objectID='4', url='javascript:alert(1)'),
                dict(base, objectID='5', title=''),
                {'objectID': '6'},
            ]})
        response = self.run_search(handler)
        self.assertEqual(response.status_code, 200)
        items = response.json()
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]['score'], 5)
        self.assertEqual(items[0]['source'], 'hackernews')
        self.assertEqual(items[1]['url'], 'https://news.ycombinator.com/item?id=3')

    def test_empty_is_success(self):
        response = self.run_search(lambda request: httpx.Response(200, json={'hits': []}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_upstream_failures_are_not_empty_success(self):
        def timeout(request):
            raise httpx.ReadTimeout('timeout', request=request)
        for handler in [timeout, lambda r: httpx.Response(429),
                        lambda r: httpx.Response(200, text='broken json'),
                        lambda r: httpx.Response(200, json={'hits': None})]:
            with self.subTest(handler=handler):
                self.assertEqual(self.run_search(handler).status_code, 502)

    def run_aggregate(self, handler):
        client_class = httpx.AsyncClient
        with patch('search.httpx.AsyncClient', side_effect=lambda **kwargs: client_class(transport=httpx.MockTransport(handler), **kwargs)):
            with TestClient(app) as client:
                return client.get('/search/all', params={'q': 'Copilot', 'days': 7})

    def feed(self):
        now = datetime.now(timezone.utc)
        recent = format_datetime(now - timedelta(hours=1))
        old = format_datetime(now - timedelta(days=10))
        return f"""<rss><channel>
          <item><title>Copilot update</title><description>&lt;p&gt;New tools&lt;/p&gt;</description><link>https://github.blog/update#rss</link><guid>rss1</guid><pubDate>{recent}</pubDate></item>
          <item><title>Older Copilot</title><link>https://github.blog/old</link><pubDate>{old}</pubDate></item>
          <item><title>Unrelated</title><description>Other news</description><link>https://github.blog/other</link><pubDate>{recent}</pubDate></item>
          <item><title>Copilot summary match</title><description>&lt;b&gt;copilot&lt;/b&gt; news</description><link>https://github.blog/summary</link><pubDate>{recent}</pubDate></item>
          <item><title>Copilot unsafe</title><link>javascript:alert(1)</link><pubDate>{recent}</pubDate></item>
          <item><title>Copilot invalid date</title><link>https://github.blog/invalid</link><pubDate>invalid</pubDate></item>
        </channel></rss>"""

    def test_aggregation_rss_filtering_dedup_and_order(self):
        def handler(request):
            if request.url.host == 'github.blog':
                return httpx.Response(200, text=self.feed())
            date = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
            return httpx.Response(200, json={'hits': [
                {'objectID': '1', 'title': 'Copilot from HN', 'url': 'https://github.blog/update#hn', 'created_at': date},
                {'objectID': '2', 'title': 'Another Copilot', 'url': 'https://example.com/second', 'created_at': date},
            ]})
        response = self.run_aggregate(handler)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['results']), 3)
        self.assertEqual([s['count'] for s in data['sources']], [2, 2])
        self.assertEqual(data['results'][0]['source'], 'github_blog')
        self.assertEqual(data['results'][0]['content'], 'copilot news')
        self.assertTrue(all(s['status'] == 'ok' for s in data['sources']))

    def test_partial_failure_preserves_healthy_results(self):
        def handler(request):
            if request.url.host == 'github.blog':
                return httpx.Response(200, text=self.feed())
            return httpx.Response(503)
        response = self.run_aggregate(handler)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['results']), 2)
        self.assertEqual(response.json()['sources'][0]['status'], 'error')
        self.assertEqual(response.json()['sources'][1]['status'], 'ok')

    def test_rss_failure_and_total_failure(self):
        for rss in ['bad xml', '<html/>']:
            def handler(request):
                if request.url.host == 'github.blog':
                    return httpx.Response(200, text=rss)
                return httpx.Response(200, json={'hits': []})
            response = self.run_aggregate(handler)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['sources'][1]['status'], 'error')
        response = self.run_aggregate(lambda request: httpx.Response(503))
        self.assertEqual(response.status_code, 502)
        self.assertTrue(all(s['status'] == 'error' for s in response.json()['detail']['sources']))

    def test_input_validation(self):
        with TestClient(app) as client:
            for params in [{'q': '  '}, {'q': 'x' * 101}, {'q': 'Claude', 'days': 0}, {'q': 'Claude', 'days': 31}, {}]:
                self.assertEqual(client.get('/search', params=params).status_code, 422)

    def test_google_news_selection_and_failure(self):
        client_class = httpx.AsyncClient
        requests = []
        def handler(request):
            requests.append(request)
            self.assertEqual(request.url.host, 'news.google.com')
            self.assertIn('"Copilot"', request.url.params['q'])
            self.assertIn('when:7d', request.url.params['q'])
            return httpx.Response(200, text=self.feed())
        with patch('search.httpx.AsyncClient', side_effect=lambda **kwargs: client_class(transport=httpx.MockTransport(handler), **kwargs)):
            with TestClient(app) as client:
                response = client.get('/search/all', params={'q': 'Copilot', 'sources': 'google_news'})
                self.assertEqual(response.status_code, 200)
                self.assertEqual([s['source'] for s in response.json()['sources']], ['google_news'])
                self.assertEqual(len(requests), 1)
                self.assertTrue(all(item['source'] == 'google_news' for item in response.json()['results']))
                self.assertEqual(client.get('/search/all', params={'q': 'Copilot', 'sources': 'unknown'}).status_code, 422)
        with patch('search.httpx.AsyncClient', side_effect=lambda **kwargs: client_class(transport=httpx.MockTransport(lambda request: httpx.Response(503)), **kwargs)):
            with TestClient(app) as client:
                self.assertEqual(client.get('/search/all', params={'q': 'Copilot', 'sources': 'google_news'}).status_code, 502)

if __name__ == '__main__':
    unittest.main()
