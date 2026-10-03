import json
import unittest
from unittest.mock import patch
import httpx
from fastapi.testclient import TestClient
from main import app

class AITests(unittest.TestCase):
    payload = {'keyword': 'Copilot', 'title': 'Copilot update', 'content': 'New code completion features'}
    valid = {'relevance': 90, 'relevance_reason': '直接討論 Copilot', 'importance': 'high', 'summary': 'Copilot 更新程式補全功能'}

    def call(self, handler):
        client_class = httpx.AsyncClient
        with patch.dict('os.environ', {'OPENROUTER_API_KEY': 'test-only-not-a-real-key', 'OPENROUTER_MODEL': 'test/model'}):
            with patch('ai.httpx.AsyncClient', side_effect=lambda **kwargs: client_class(transport=httpx.MockTransport(handler), **kwargs)):
                with TestClient(app) as client:
                    return client.post('/analyze', json=self.payload)

    def test_valid_analysis_and_request_contract(self):
        def handler(request):
            self.assertEqual(str(request.url), 'https://openrouter.ai/api/v1/chat/completions')
            body = json.loads(request.content)
            self.assertEqual(body['model'], 'test/model')
            self.assertEqual(body['max_tokens'], 500)
            self.assertEqual(body['response_format'], {'type': 'json_object'})
            self.assertEqual(json.loads(body['messages'][1]['content']), self.payload)
            return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(self.valid)}}]})
        response = self.call(handler)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['analysis'], self.valid)
        self.assertEqual(response.json()['verification'], 'unverified')

    def test_missing_settings_does_not_call_provider(self):
        with patch.dict('os.environ', {'OPENROUTER_API_KEY': '', 'OPENROUTER_MODEL': ''}):
            with patch('ai.httpx.AsyncClient') as provider:
                with TestClient(app) as client:
                    self.assertEqual(client.post('/analyze', json=self.payload).status_code, 503)
                provider.assert_not_called()

    def test_failure_does_not_invent_analysis(self):
        def timeout(request):
            raise httpx.ReadTimeout('timeout', request=request)
        handlers = [timeout, lambda r: httpx.Response(401), lambda r: httpx.Response(429),
                    lambda r: httpx.Response(200, json={'choices': []}),
                    lambda r: httpx.Response(200, json={'choices': [{'message': {'content': 'not json'}}]})]
        for handler in handlers:
            response = self.call(handler)
            self.assertEqual(response.status_code, 502)
            self.assertNotIn('analysis', response.json())

    def test_invalid_model_output_rejected(self):
        for changes in [{'relevance': 101}, {'relevance': '90'}, {'relevance': True},
                        {'importance': 'unknown'}, {'summary': ''}, {'isReal': True}]:
            output = dict(self.valid, **changes)
            response = self.call(lambda request: httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(output)}}]}))
            self.assertEqual(response.status_code, 502)

    def test_input_limits(self):
        with TestClient(app) as client:
            for changes in [{'keyword': ' '}, {'title': ''}, {'content': 'x' * 2001}]:
                self.assertEqual(client.post('/analyze', json=dict(self.payload, **changes)).status_code, 422)

if __name__ == '__main__':
    unittest.main()
