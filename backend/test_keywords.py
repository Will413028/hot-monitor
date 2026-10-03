import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database import Base, Keyword, get_session
from main import app

class KeywordTests(unittest.TestCase):
    def test_keyword_lifecycle_and_persistence(self):
        with tempfile.TemporaryDirectory() as tmp:
            url = f"sqlite:///{Path(tmp) / 'test.db'}"
            engine = create_engine(url, connect_args={"check_same_thread": False})
            Base.metadata.create_all(engine)
            sessions = sessionmaker(bind=engine)
            def override():
                with sessions() as session:
                    yield session
            app.dependency_overrides[get_session] = override
            try:
                with TestClient(app) as client:
                    self.assertEqual(client.get('/keywords').json(), [])
                    self.assertEqual(client.post('/keywords', json={'text': '  '}).status_code, 422)
                    self.assertEqual(client.post('/keywords', json={'text': 'x' * 101}).status_code, 422)
                    response = client.post('/keywords', json={'text': ' Claude '})
                    self.assertEqual(response.status_code, 201)
                    keyword = response.json()
                    self.assertEqual(keyword['text'], 'Claude')
                    self.assertTrue(keyword['is_active'])
                    self.assertEqual(client.post('/keywords', json={'text': 'Claude'}).status_code, 409)
                    path = f"/keywords/{keyword['id']}"
                    self.assertFalse(client.patch(path, json={'is_active': False}).json()['is_active'])
                    self.assertTrue(client.patch(path, json={'is_active': True}).json()['is_active'])
                    engine.dispose()
                    reopened = create_engine(url)
                    with sessionmaker(bind=reopened)() as session:
                        self.assertEqual(session.get(Keyword, keyword['id']).text, 'Claude')
                    reopened.dispose()
                    self.assertEqual(client.delete(path).status_code, 204)
                    self.assertEqual(client.get('/keywords').json(), [])
                    self.assertEqual(client.delete(path).status_code, 404)
                    self.assertEqual(client.patch(path, json={'is_active': True}).status_code, 404)
                    for method in ['POST', 'PATCH', 'DELETE']:
                        response = client.options('/keywords', headers={
                            'Origin': 'http://localhost:3000',
                            'Access-Control-Request-Method': method,
                            'Access-Control-Request-Headers': 'content-type',
                        })
                        self.assertEqual(response.status_code, 200)
            finally:
                app.dependency_overrides.clear()
                engine.dispose()

if __name__ == '__main__':
    unittest.main()
