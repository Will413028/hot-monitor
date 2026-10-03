import json
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

CLI = Path(__file__).resolve().parents[1] / 'skills/hot-monitor/scripts/hot_monitor.py'


class SkillTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        calls = self.calls
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass
            def serve(self):
                length = int(self.headers.get('Content-Length', 0))
                body = json.loads(self.rfile.read(length)) if length else None
                calls.append((self.command, self.path, body))
                if self.path == '/keywords/999':
                    self.send_response(404); self.end_headers(); return
                if self.command == 'DELETE':
                    self.send_response(204); self.end_headers(); return
                self.send_response(200); self.send_header('Content-Type', 'application/json'); self.end_headers()
                self.wfile.write(json.dumps({'id': 1} if self.command == 'POST' else []).encode())
            do_GET = serve
            do_POST = serve
            do_DELETE = serve
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()

    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(CLI), '--api-url', self.base, *args], text=True, capture_output=True, timeout=10)

    def test_search_sources_report_and_mutations(self):
        result = self.run_cli('search', 'AI tools', '--sources', 'hackernews,google_news', '--expand')
        self.assertEqual(result.returncode, 0, result.stderr)
        url = urlsplit(self.calls[-1][1])
        self.assertEqual(url.path, '/search/expanded')
        self.assertEqual(parse_qs(url.query)['sources'], ['hackernews', 'google_news'])
        self.assertEqual(parse_qs(url.query)['q'], ['AI tools'])
        self.assertEqual(json.loads(self.run_cli('add', 'AI').stdout), {'id': 1})
        self.assertEqual(self.calls[-1], ('POST', '/keywords', {'text': 'AI'}))
        self.assertIn('共 0 篇', self.run_cli('report', '1').stdout)
        self.assertEqual(json.loads(self.run_cli('delete', '1').stdout), {'deleted': True})

    def test_errors_return_nonzero_without_retry(self):
        result = self.run_cli('delete', '999')
        self.assertEqual(result.returncode, 1)
        self.assertIn('404', result.stderr)
        self.assertEqual(len(self.calls), 1)
        result = self.run_cli('search', 'AI', '--sources', 'invalid')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(self.calls), 1)
