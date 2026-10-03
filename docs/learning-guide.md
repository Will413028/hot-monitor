# 跟著程式學習

這個版本把參考專案的功能改寫成 Next.js／FastAPI。先跑 README 的本機入口，再按下面順序閱讀；每一步都能在畫面或測試確認行為。

## 1. 一次請求怎麼走

從 `frontend/src/app/api.ts` 的 fetch，到 `backend/main.py` 的 route，再到 `database.py` 的 Session。Next.js 負責畫面與使用者操作，FastAPI 負責驗證、資料與外部服務。試著新增相同關鍵字兩次，看唯一限制如何轉成 409。

## 2. 多來源為什麼先轉成共同資料

讀 `search.py` 的 SearchResult 與三個 adapter。HN 回 JSON，另兩個回 RSS；聚合層只處理共通欄位、來源狀態與 URL 去重。跑 `test_search.py`，觀察一個來源失敗仍可回傳其餘結果，以及「沒有結果」與「搜尋失敗」的區別。

## 3. AI 的邊界在哪裡

讀 `ai.py`：輸入先裁長度，模型輸出再以 Pydantic 驗證；合法 JSON 仍可能有錯誤內容，所以顯示未查證。原詞搜尋不依賴 Key；Query Expansion 會把額外詞真的送到搜尋 adapter。`test_expansion.py` 用只存在於新增詞的結果證明此差異。

## 4. 排程與資料庫如何互相保護

讀 `monitor.py`。程序 lock 避免同時檢查，資料庫 unique constraint 負責最終去重；兩者保護不同邊界。監控每次最多嘗試五篇新文章的 AI，失敗也計次。讀 `migrations/versions/`，理解 schema 如何在新安裝與既有資料庫一致前進。

## 5. 通知為什麼先保存再推送

新文章與 Notification 在同一 transaction。讀 `events.py`：以通知 ID 補讀、分批送 SSE、維持 heartbeat。瀏覽器重連不代表資料會自動保存；保存由 SQLite 完成。再讀 `email_delivery.py`：SMTP 是外部副作用，靠 lease／重試恢復，發送與資料庫提交不能變成同一筆 atomic transaction。

## 6. 怎麼知道真的能用

`test_*.py` 驗證 API、失敗邊界、保存與寄送流程；`frontend/tests/full-flow.spec.ts` 驗證真實瀏覽器操作；`test_skill.py` 用本機 HTTP server 驗證 CLI。E2E 資料庫與 `.next-e2e` 輸出獨立，避免測試污染正在使用的應用。測試用 mock AI／SMTP，驗證的是程式契約，不是真模型品質或實際收件。

進階練習：新增一個來源 adapter，讓它通過共同 schema 與部分失敗測試；接著沿用前端來源選擇和已保存結果篩選。完成後先檢查它是否改變原本去重、成本上限或時間範圍的契約。
