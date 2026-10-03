# Hot Monitor

Next.js + FastAPI 的本機熱點監控工具。瀏覽器直接呼叫 API，SQLite 保存關鍵字、文章、AI 分析與通知。

程式閱讀與練習順序見 [學習導讀](docs/learning-guide.md)。

## 功能

- 關鍵字新增、列表、啟用／暫停、刪除與檢查狀態。
- Hacker News、GitHub Blog RSS、Google News RSS 搜尋；來源選擇、時間範圍、URL 去重。
- AI Query Expansion：原詞加最多兩個別名，實際參與各來源搜尋。
- OpenRouter 相關性、理由、重要程度與繁體中文摘要；模型輸出嚴格驗證，內容標示未查證。
- 手動／定時檢查、結果保存、防重疊、重複文章不重存；同篇文章可屬於多個關鍵字。
- 已保存文章按來源、重要程度、相關性、時間篩選，按時間／相關性／HN 分數排序，支援分頁。
- 持久化通知、已讀狀態、SSE 即時推送與斷線補讀。
- 高／緊急重要程度的通知可排入 SMTP Email，失敗可重試；支援 STARTTLS 與 SMTP SSL。
- Agent Skill 與標準庫 CLI、Docker Compose 部署入口、API／瀏覽器端到端測試。

## 本機啟動

需求：Node.js 20.9+（容器用 24）、Python 3.13、uv。

在 backend 目錄：

```bash
uv venv --python 3.13
uv pip install -r requirements.txt
.venv/bin/alembic upgrade head
.venv/bin/uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

在 frontend 目錄的另一個終端：

```bash
npm ci
npm run dev -- --hostname 127.0.0.1 --port 3000
```

- 前端：http://127.0.0.1:3000
- API 文件：http://127.0.0.1:8000/docs
- 健康檢查：http://127.0.0.1:8000/health

本機 SQLite 檔為 backend/hot-monitor.db；可用 HOT_MONITOR_DB 指定絕對路徑。schema 由 Alembic migrations 管理，不以 create_all 取代正式 migration。

## 本機 production 入口

結束同 ports 的開發服務後，backend 先跑 migration，再執行：

```bash
.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000 --workers 1
```

frontend 的 npm run build 使用 Webpack，並自動將 public 與靜態資產放進 standalone 產物，再執行：

```bash
HOSTNAME=127.0.0.1 PORT=3000 npm run start
```

前端 production API 位址在 build 時決定；預設對應本機 8000。跨 host 時須調整 NEXT_PUBLIC_API_BASE_URL 和後端 CORS_ORIGINS。

## AI 與 Email 設定

以 backend/config.example 為欄位參考，在本機 backend/.env 保存設定。API 啟動時載入；變更設定後重啟。API Key 只在後端使用，不輸出至瀏覽器。credential 檔與資料庫不進 Git／Docker image。

- OPENROUTER_API_KEY、OPENROUTER_MODEL：選擇支援 JSON 輸出的模型。未設定時 AI API 回傳 503；上游錯誤／非法回應回傳 502，沒有假分數。
- MONITOR_ENABLED：預設 true；MONITOR_INTERVAL_SECONDS 預設 300（最低 10）。啟動／暫停排程按鈕僅影響目前程序，重啟後遵循環境設定。
- MONITOR_AI_ENABLED：預設 false；啟用時每次檢查最多分析五篇新文章，計算的是嘗試次數，不是成功數。
- MONITOR_EXPANSION_ENABLED：預設 false；啟用時每次檢查額外做一次搜尋詞擴展。失敗會回原詞搜尋並增加 ai_error_count。
- EMAIL_ENABLED：預設 false；SMTP_HOST、SMTP_FROM、SMTP_TO 必填。SMTP_PORT 預設 587，SMTP_STARTTLS 預設 true。SMTP_SSL=true 時預設 port 465；認證可填 SMTP_USERNAME、SMTP_PASSWORD。
- CORS_ORIGINS：逗號分隔的允許前端來源，預設本機 port 3000。
- NEXT_PUBLIC_API_BASE_URL：前端 API 位址，預設 http://127.0.0.1:8000；production build 時即決定，變更後要重新 build。

Email 只為已分析為 high／urgent 的文章排隊；手動分析保存結果也能啟動排隊。Email delivery 每 30 秒處理最多 20 則，失敗最多三次，重試退避；發送中的工作用十分鐘 lease 復原。SMTP 沒有 exactly-once 保證：發送成功但保存 sent 前程序中斷，復原後可能重複發送。不可將 SMTP 測試視為真實收件證明。

## 搜尋與監控契約

Google News 是全網新聞索引，不是任意網站全文搜尋。GitHub Blog 只涵蓋最新 RSS 文章的標題／摘要；HN 是 Algolia story 搜尋。三個 adapter 轉成共同 SearchResult，未取得原文時不捏造全文。Google News URL 是其轉址連結，跨來源去重只能消除相同 URL（忽略 fragment），不能判定不同 URL 是同一新聞。

原詞搜尋不呼叫模型。擴展搜尋每次最多一次模型請求、三次 HN 請求、一次 GitHub RSS 與一次 Google News RSS；模型生成的別名先做長度／數量與大小寫去重。畫面顯示實際搜尋詞與各來源狀態。partial 表示某些詞查詢失敗；所有來源失敗回傳 502，成功無結果才是空清單。

定時監控預設 HN、GitHub Blog 與 Google News，每五分鐘只檢查啟用的關鍵字；手動檢查也可用於暫停關鍵字。監控按七天查詢，保存最多每來源二十篇（擴展詞會增加 HN 候選），AI 作業獨立限額。後端關閉時不監控，重啟後重新計時，不補跑離線期間。

單程序 lock 避免手動與排程重疊；資料庫的 (keyword_id, normalized_url) 唯一限制負責最終去重。同篇文章可以屬於不同關鍵字。重複文章不更新內容與互動數字。刪除關鍵字會刪除其保存結果與通知。

新文章和通知在同一 transaction 保存；SSE 從 SQLite 按遞增通知 ID 讀取，每秒查詢、每十五秒 heartbeat，支援 Last-Event-ID／after 補讀。瀏覽器重新整理會先讀最新五十則通知，再訂閱後續事件；所有保存結果仍可用 API 分頁查詢。

## API

完整 schema 以 /docs 為準。

| API | 行為 |
|---|---|
| GET /keywords、POST /keywords | 列表／新增 |
| PATCH /keywords/{id}、DELETE /keywords/{id} | 啟用／暫停／刪除 |
| GET /search | HN 單來源 |
| GET /search/all、GET /search/expanded | 原詞／AI 擴展，多次 sources 參數選來源 |
| POST /analyze | 暫存文章的 AI 分析 |
| POST /keywords/{id}/check | 檢查與保存 |
| GET /keywords/{id}/hotspots | 保存結果、limit／offset／source／importance／min_relevance／days／sort |
| POST /hotspots/{id}/analyze | 分析並保存 |
| GET /notifications、PATCH /notifications/{id}/read | 通知列表／已讀 |
| GET /events | SSE |
| GET /monitor/status、PATCH /monitor/config | 排程狀態／啟用暫停 |

## 驗證

backend：

```bash
.venv/bin/python -m unittest discover
.venv/bin/alembic check
```

frontend：

```bash
npm run lint
npm run build
PLAYWRIGHT_CHANNEL=chrome npm run test:e2e
```

E2E 用本機 Chrome；沒有 Chrome 時先執行 npx playwright install chromium，再用 npm run test:e2e。測試用獨立 SQLite 與 mock provider，不碰本機資料、不呼叫真實 AI／SMTP；frontend 測試用 .next-e2e 避免干擾既有開發服務。完整流程覆蓋關鍵字、搜尋、AI、保存、篩選、SSE、已讀狀態與排程控制。

若測試 API 的 18000 port 已被占用，可用 E2E_API_PORT=18020 PLAYWRIGHT_CHANNEL=chrome npm run test:e2e；測試仍只接受自己啟動的 API。

## Docker

在專案根目錄執行 docker compose up --build。API 與 web ports 只 bind 到 127.0.0.1；API 使用單一 worker，資料庫使用 named volume。Compose 預設不啟用 AI／Email，可用獨立本機 override 的 env_file 與環境設定啟用，credential 不複製進 image。

此版本面向單使用者本機／可信 host；若要公開提供多人使用，觸發重新設計登入與資料隔離、排程的跨程序協調及通知 delivery 邊界，不能只增加 uvicorn workers。

## Agent Skill

skills/hot-monitor 可複製到 Agent 支援的 skills 目錄。CLI 不需要額外套件，API 必須已啟動：

```bash
python3 skills/hot-monitor/scripts/hot_monitor.py search Copilot
python3 skills/hot-monitor/scripts/hot_monitor.py keywords
python3 skills/hot-monitor/scripts/hot_monitor.py report 1
```

HOT_MONITOR_API_URL 可指定服務位址。所有 mutation 都是明確的 subcommand；網路失敗不自動重試 mutation。

參考：[原專案](https://github.com/liyupi/yupi-hot-monitor)、[OpenRouter API](https://openrouter.ai/docs/api_reference/overview)、[APScheduler](https://apscheduler.readthedocs.io/en/3.x/modules/schedulers/asyncio.html)、[SSE](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events)。
