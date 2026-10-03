#!/usr/bin/env python3
import argparse
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def request(base, path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = Request(base.rstrip("/") + path, data=data, method=method, headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=190) as response:
        return json.load(response) if response.status != 204 else {"deleted": True}


def report(items):
    lines = ["# Hot Monitor 報告", f"共 {len(items)} 篇已保存文章（最多 100 篇）", ""]
    for item in items:
        lines.extend([f"- [{item['title']}]({item['url']})", f"  - 來源：{item['source']} · 發布：{item['published_at']}"])
        if item.get("analysis_json"):
            analysis = json.loads(item["analysis_json"])["analysis"]
            lines.append(f"  - 相關性：{analysis['relevance']}/100 · 重要程度：{analysis['importance']}")
            lines.append(f"  - 摘要：{analysis['summary']}（未查證）")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Hot Monitor API client")
    parser.add_argument("--api-url", default=os.getenv("HOT_MONITOR_API_URL", "http://127.0.0.1:8000"))
    commands = parser.add_subparsers(dest="command", required=True)
    search = commands.add_parser("search")
    search.add_argument("query")
    search.add_argument("--days", type=int, default=7, choices=range(1, 31))
    search.add_argument("--sources", default="hackernews,github_blog,google_news")
    search.add_argument("--expand", action="store_true")
    commands.add_parser("keywords")
    commands.add_parser("notifications")
    commands.add_parser("add").add_argument("text")
    for name in ("pause", "resume", "check", "delete", "analyze"):
        commands.add_parser(name).add_argument("id", type=int)
    for name in ("hotspots", "report"):
        sub = commands.add_parser(name)
        sub.add_argument("id", type=int)
        sub.add_argument("--sort", choices=["time", "score", "relevance"], default="time")
        sub.add_argument("--min-relevance", type=int)
    args = parser.parse_args()
    method, body = "GET", None
    if args.command == "search":
        sources = [source.strip() for source in args.sources.split(",") if source.strip()]
        if not sources or any(source not in {"hackernews", "github_blog", "google_news"} for source in sources):
            parser.error("Invalid search sources")
        params = [("q", args.query), ("days", args.days)] + [("sources", source) for source in sources]
        path = f"/search/{'expanded' if args.expand else 'all'}?{urlencode(params)}"
    elif args.command in {"keywords", "notifications"}:
        path = f"/{args.command}"
    elif args.command == "add":
        path, method, body = "/keywords", "POST", {"text": args.text}
    elif args.command in {"pause", "resume"}:
        path, method, body = f"/keywords/{args.id}", "PATCH", {"is_active": args.command == "resume"}
    elif args.command == "check":
        path, method = f"/keywords/{args.id}/check", "POST"
    elif args.command == "delete":
        path, method = f"/keywords/{args.id}", "DELETE"
    elif args.command == "analyze":
        path, method = f"/hotspots/{args.id}/analyze", "POST"
    else:
        params = {"limit": 100, "sort": args.sort}
        if args.min_relevance is not None:
            params["min_relevance"] = args.min_relevance
        path = f"/keywords/{args.id}/hotspots?{urlencode(params)}"
    try:
        result = request(args.api_url, path, method, body)
        print(report(result) if args.command == "report" else json.dumps(result, ensure_ascii=False, indent=2))
    except HTTPError as exc:
        print(f"Hot Monitor HTTP error: {exc.code}", file=sys.stderr)
        return 1
    except (URLError, TimeoutError, ValueError, OSError):
        print("Hot Monitor request failed; check server availability and settings", file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
