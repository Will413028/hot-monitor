# Hot Monitor

Local single-process Next.js + FastAPI monitoring application. Product contracts are in README.md and docs/completion.md.

- Backend working directory: backend. Install requirements into .venv, run `.venv/bin/alembic upgrade head`, then `.venv/bin/uvicorn main:app --reload --host 127.0.0.1 --port 8000`.
- Backend checks: `.venv/bin/python -m unittest discover` and `.venv/bin/alembic check` from backend.
- Frontend working directory: frontend. Checks: `npm run lint`, `npm run build`, `npm run test:e2e` (a Playwright browser must be installed; PLAYWRIGHT_CHANNEL=chrome uses installed Chrome).
- Run one API worker because scheduling and monitor locks belong to one process. SQLite notification IDs are monotonic for SSE replay.
- LLM output is unverified and strictly validated. Do not turn a provider failure into fabricated analysis or an empty successful source.
- Keep credentials in backend/.env or the runtime environment; never put them in browser settings or artifacts.
