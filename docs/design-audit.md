# 沿用機制盤點

| 機制 | 原必要條件 | 今天是否成立 | 決定與重新評估條件 |
|---|---|---|---|
| SQLite／整數 ID | 單機保存、低流量 | README 明定單使用者本機，無既有正式部署 | 保留；Notification 用 AUTOINCREMENT 保持 SSE cursor 單調，跨 host／多使用者時重評 |
| APScheduler 與程序 lock | 單一 API process | Dockerfile --workers 1、Compose local bind | 保留；多 worker／獨立 worker 時換跨程序協調，不把 local lock 當分散式鎖 |
| 來源共同 SearchResult | 多 provider 的資料不同 | HN JSON 與兩種 RSS | 保留 adapter，聚合只做來源狀態、排序、URL 去重；新增來源時用相同 schema |
| OpenRouter JSON 與嚴格 Pydantic | 外部模型輸出不可信 | 模型無法保證正確數字或欄位 | 保留；更換 structured-output 模型時驗 schema，內容仍未查證 |
| 原詞與擴展搜尋分開 | 使用者明確決定付費作業 | 不設 Key 仍能搜尋，AI mock 驗證 | 保留，UI 有獨立按鈕，排程 AI flags 預設 false；需要自動成本預算時重評 |
| 文章＋通知同 transaction | 不允許 article 有了但 notice 丟失 | 保存由同一 Monitor.check 寫入 SQLite | 保留；新的資料庫邊界／跨服務時重評可靠發佈 |
| SSE durable cursor | 前端只需要單向事件且可能斷線 | MDN EventSource 支援 id 及 reconnect；events.py 從通知表補讀 | 選 SSE，相較 WebSocket 少一個雙向 session 邊界；雙向互動時重評 |
| SMTP lease／重試 | 外部發送不能包含在資料庫 transaction | send_email 在 commit 後，EmailDelivery 另行處理 | 三次嘗試、十分鐘 lease；接受 at-least-once 邊界，要求收件 exactly-once 時換具冪等契約的 provider |
| API 直連 | 使用者明確選第一種分工 | Next.js 只做 UI，FastAPI 擁有資料／AI | 保留；需要集中 session 或同源部署時重評 BFF |
| FK cascade | 外鍵已啟用且關聯宣告 ON DELETE CASCADE | 正式連線與刪除回歸測試皆啟用外鍵 | 資料庫統一負責刪除，移除 API 的重複子表 DELETE |
| UTC-naive SQLite 時間 | SQLite 缺少原生 timezone 型別 | 所有保存使用 UTC，API 邊界補 UTC timezone | 保留；更換資料庫時重新確認時間型別 |
| analysis JSON 與投影 | 保存完整分析且需 SQL 篩選 | 手動與自動分析同步寫 relevance／importance | 保留；需要分析歷史時重評獨立分析表 |
| 前端重新讀取 | 單使用者且資料量小 | mutation 與通知後重新載入 | 保留；使用者數或通知頻率增加時重評快取 |
| 外部作業後重新讀取 | 搜尋／模型期間可能刪除資料 | SQLite 一般 rowid 可重用 | Keyword 比對原查詢文字，文章比對 keyword／URL／saved_at；重播通知使用不重用 ID，回歸測試覆蓋不同資料重用 ID |
| 監控預設來源 | 原先只有兩個 provider | Google News 已有共同 adapter | 預設三來源，共用保存／通知；不另建新聞監控旁路 |
| 舊文章補通知 | 舊資料可能沒有 Notification | 手動分析也可啟動 Email 排隊 | 缺通知時與分析同 transaction 補建，既有狀態不重送 |
| standalone 產物 | Next build 不自帶 public／static | 本機與 Docker 都需要完整資產 | postbuild 統一組裝；消費端只啟動產物，build 明定已驗證的 Webpack |
