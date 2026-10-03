---
name: hot-monitor
description: Search news across Hacker News, GitHub Blog and Google News, manage monitoring keywords, inspect saved hotspots, and generate reports through a running Hot Monitor API. Use for Hot Monitor searches and reports; excludes unrelated general browsing.
---

# Hot Monitor

Use `scripts/hot_monitor.py` with Python 3.10+ (standard library only). The FastAPI service must be running; default address is http://127.0.0.1:8000. Override with HOT_MONITOR_API_URL or --api-url. Do not start another server merely because one request failed.

## Read operations

```bash
python scripts/hot_monitor.py search "Copilot" --sources hackernews,github_blog,google_news --days 7
python scripts/hot_monitor.py keywords
python scripts/hot_monitor.py hotspots 1 --sort relevance --min-relevance 50
python scripts/hot_monitor.py report 1
python scripts/hot_monitor.py notifications
```

Search returns JSON with `results`, `sources` and `queries`. Treat `partial`/`error` sources as incomplete coverage; zero results with failed sources does not mean no news exists. Reports link to articles and include source, publication time and stored AI analysis. AI analysis is not fact verification.

## Changes requested by the user

```bash
python scripts/hot_monitor.py add "Copilot"
python scripts/hot_monitor.py pause 1
python scripts/hot_monitor.py resume 1
python scripts/hot_monitor.py check 1
python scripts/hot_monitor.py analyze 42
python scripts/hot_monitor.py delete 1
```

`check` searches and saves articles for one keyword, even when paused. `analyze` acts on a saved article ID and may incur model cost. `search --expand` also calls the model. Credentials stay in the backend environment; the CLI never takes or prints them. Delete removes the keyword, its articles and its notifications; apply the current user's authorization rules.

Exit code 1 means HTTP/network failure. Error messages go to stderr; successful JSON or Markdown goes to stdout. Do not retry mutating calls automatically after a timeout: read back the state first.
