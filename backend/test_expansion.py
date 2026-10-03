import json
import unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from unittest.mock import patch
import httpx
from fastapi.testclient import TestClient
from main import app

class ExpansionTests(unittest.TestCase):
    def call(self, handler):
        client_class = httpx.AsyncClient
        with patch.dict('os.environ', {'OPENROUTER_API_KEY': 'test-only-not-a-real-key', 'OPENROUTER_MODEL': 'test/model'}):
            with patch('httpx.AsyncClient', side_effect=lambda **kwargs: client_class(transport=httpx.MockTransport(handler), **kwargs)):
                with TestClient(app) as client:
                    return client.get('/search/expanded', params={'q': '人工智慧', 'days': 7})

    def test_expanded_terms_reach_both_sources(self):
        calls = []
        def handler(request):
            calls.append(request)
            if request.url.host == 'openrouter.ai':
                body = json.loads(request.content)
                self.assertEqual(json.loads(body['messages'][1]['content']), {'keyword': '人工智慧'})
                return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps({'terms': ['AI', 'Artificial Intelligence']})}}]})
            if request.url.host == 'github.blog':
                date = format_datetime(datetime.now(timezone.utc) - timedelta(hours=1))
                return httpx.Response(200, text=f'<rss><channel><item><title>AI release</title><link>https://github.blog/ai</link><pubDate>{date}</pubDate></item></channel></rss>')
            term = request.url.params['query']
            hits = [] if term == '人工智慧' else [{'objectID': term, 'title': 'AI update', 'url': 'https://example.com/same', 'created_at': datetime.now(timezone.utc).isoformat()}]
            return httpx.Response(200, json={'hits': hits})
        response = self.call(handler)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['queries'], ['人工智慧', 'AI', 'Artificial Intelligence'])
        self.assertEqual(len(data['results']), 2)
        self.assertEqual({r.url.params['query'] for r in calls if r.url.host == 'hn.algolia.com'}, set(data['queries']))
        self.assertEqual(sum(r.url.host == 'github.blog' for r in calls), 1)
        self.assertEqual(sum(r.url.host == 'openrouter.ai' for r in calls), 1)
        self.assertEqual(data['sources'][1]['count'], 1)

    def test_partial_query_failure_keeps_results(self):
        def handler(request):
            if request.url.host == 'openrouter.ai':
                return httpx.Response(200, json={'choices': [{'message': {'content': '{"terms":["AI"]}'}}]})
            if request.url.host == 'github.blog':
                return httpx.Response(200, text='<rss><channel/></rss>')
            if request.url.params['query'] == '人工智慧':
                return httpx.Response(503)
            return httpx.Response(200, json={'hits': [{'objectID': '1', 'title': 'AI', 'url': 'https://example.com/ai', 'created_at': datetime.now(timezone.utc).isoformat()}]})
        data = self.call(handler).json()
        self.assertEqual(len(data['results']), 1)
        self.assertEqual(data['sources'][0]['status'], 'partial')

    def test_deduplicated_terms_and_invalid_expansion(self):
        for terms, expected in [(['人工智慧', '人工智慧'], ['人工智慧']), (['AI', 'ai'], ['人工智慧', 'AI']), ([], ['人工智慧'])]:
            def handler(request):
                if request.url.host == 'openrouter.ai':
                    return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps({'terms': terms})}}]})
                if request.url.host == 'github.blog':
                    return httpx.Response(200, text='<rss><channel/></rss>')
                return httpx.Response(200, json={'hits': []})
            self.assertEqual(self.call(handler).json()['queries'], expected)
        for terms in [['a', 'b', 'c'], [' '], [123]]:
            response = self.call(lambda r: httpx.Response(200, json={'choices': [{'message': {'content': json.dumps({'terms': terms})}}]}))
            self.assertEqual(response.status_code, 502)

    def test_missing_configuration_stops_before_search(self):
        with patch.dict('os.environ', {'OPENROUTER_API_KEY': '', 'OPENROUTER_MODEL': ''}):
            with patch('httpx.AsyncClient') as provider:
                with TestClient(app) as client:
                    self.assertEqual(client.get('/search/expanded', params={'q': 'AI'}).status_code, 503)
                provider.assert_not_called()

if __name__ == '__main__':
    unittest.main()
