---
title: Hot Monitor 以持久通知表支援 SSE 補讀
date: 2026-10-01
status: active
tags: [personal, decision, fastapi]
---

# 以持久通知表支援 SSE 補讀

## Context

原有專案已能搜尋並保存文章，尚未提供即時通知。Will 要求完成所有功能；通知需保存讀取狀態，重整與斷線後能取回。此 ADR 記錄本次實作已落地、可局部替換的通知方式。

**約束：**
- `external` Will 選定 Next.js／FastAPI，先完成程式與 mock 驗證；來源為本次專案對話。
- `inherited` 單使用者本機、SQLite、單 API process；目前仍無正式公開部署，README 與 Docker workers=1 明定此範圍。
- `inherited` 前端只需要收到新文章提示，操作仍走 REST；尚無雙向互動需求。

## Options Considered

- **A. SSE（基準、選用）**：單向通知使用瀏覽器 EventSource，支援事件 ID 與自動重連；[MDN 官方文件](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events)。通知表補讀由應用實作，SSE 本身不保證資料持久化。
- **B. 定時輪詢**：每隔數秒讀通知表，連線管理最簡單；代價是固定延遲與空查詢。
- **C. WebSocket**：能雙向即時互動；代價是本專案額外承擔 session、重連與重播管理，現有 REST 已處理操作。

## Decision

選 SSE 而非輪詢或 WebSocket。新文章與 Notification 同一 SQLite transaction 保存；事件從通知表依 ID 補讀，Notification 使用 AUTOINCREMENT。前端先載入最近通知，再從最大 ID 建立 EventSource，重連使用 Last-Event-ID。

## Rationale

SSE 相較輪詢能及時顯示通知，且不需要 WebSocket 的雙向管理。代價是持續連線、heartbeat 與每秒資料庫補讀；對本機單使用者可接受。保留通知表作為唯一保存來源，避免程序重啟使記憶體佇列遺失。通知 ID 不重用，避免刪除後的新通知被既有 cursor 跳過。

## Expected Outcome

文章保存後可出現通知；重整仍保留讀取狀態；以先前 ID 重連可補讀後續事件。由 `backend/test_delivery.py` 與 `frontend/tests/full-flow.spec.ts` 驗證，不承諾瀏覽器展示 exactly-once。

## Invariants

- 文章與通知一起提交；事件內容來自已提交的通知。
- 前端按通知 ID 去重；API 保留最大 100 筆／次的分批補讀。

## Revocation Triggers

- 出現雙向即時互動時重評 WebSocket。
- 改多使用者、多 host 或需刪除通知歷史時，重評重播、游標保存及資料保留契約。

## Review Notes

初版。

## Related

- 本 ADR 即原始決策紀錄，無外部來源文件；使用者要求與實作取捨源於本次對話。
- [SQLite AUTOINCREMENT 官方文件](https://www.sqlite.org/autoinc.html)；實作取回入口為 `backend/events.py` 與 `backend/database.py`。
- 沒有獨立 Lessons Rules；本次單專案實作經驗不另抽跨專案規則。
