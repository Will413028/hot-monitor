# 完成功能與驗收

本機學習用單程序服務，Next.js 直接呼叫 FastAPI。SQLite 保存資料，無既有正式部署。

- [x] 前後端骨架、關鍵字管理、搜尋與 Query Expansion、手動 AI 分析、排程與結果保存
- [x] SSE 與持久化通知、讀取狀態、Email delivery
- [x] AI 分析保存、自動分析的數量限制、篩選排序
- [x] 全網新聞搜尋來源、獨立搜尋輸入
- [x] Agent Skill 與 CLI
- [x] 可重現啟動／部署入口、瀏覽器驗證
- [x] 獨立 design-review、紀錄知識與決策

## 驗證證據

| 項目 | 結果 |
|---|---|
| backend／CLI | 37 tests 通過；含 transaction rollback、失敗 AI 預算、ID 重用的先失敗再通過回歸 |
| Browser | Chrome 完整 E2E 26.6 秒通過（三來源保存與通知）；mock AI／來源、獨立 SQLite |
| Frontend | lint、production build 通過 |
| Native production | API migration／CRUD／重啟保存通過；standalone HTML 與 7 個 JS／CSS 資產 HTTP 200 |
| DB | Alembic check 通過，schema 無差異 |
| 公開搜尋 | HN／GitHub Blog／Google News live 成功，聚合 43 篇 |
| Agent Skill | quick_validate 通過，CLI HTTP integration 通過 |
| Design review | B finding 改 1；複核 NO DESIGN FINDINGS |
| 知識庫 | lint-rules／check-links 通過 |
| Docker 額外驗證 | Compose config 通過；API image 的 no-compile 診斷變體曾建置成功並執行三個 migration，但容器未完成就緒、web image 未完成。Desktop import 異常緩慢，Colima BuildKit driver 連線逾時；最後恢復標準 pip 安裝，當前 Dockerfile 未完成容器驗收 |

Docker 未驗證項不視為容器部署成功；本機 production 入口另行驗證。不需要發布遠端服務。

不變量：未設定 credentials 不捏造成功；LLM 結果未查證；模型輸出嚴格驗證；同一文章可歸多個關鍵字；通知與文章在同一 SQLite transaction 保存；SSE 從保存的通知補讀。

完成定義：功能清單皆有可執行入口與測試；外部付費 AI／SMTP 使用 mock 驗證；未配置實際服務的限制清楚記錄；不發布遠端服務。
