"use client";
import { useEffect, useState } from "react";
import { api, AnalysisResponse, buttonClass, importanceNames, inputClass, Keyword, sourceNames } from "./api";

type Hotspot = { id: number; title: string; url: string; source: string; content: string; published_at: string; saved_at: string; relevance: number | null; importance: string | null; analysis_json: string | null };
type Status = { enabled: boolean; interval_seconds: number; running: boolean; next_run_at: string | null; ai_enabled: boolean; email_enabled: boolean };

export default function MonitorPanel({ keywords, revision, onChanged }: { keywords: Keyword[]; revision: number; onChanged: () => void }) {
  const [selected, setSelected] = useState("");
  const [items, setItems] = useState<Hotspot[]>([]);
  const [status, setStatus] = useState<Status | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [source, setSource] = useState("");
  const [importance, setImportance] = useState("");
  const [minRelevance, setMinRelevance] = useState("");
  const [days, setDays] = useState("");
  const [sort, setSort] = useState("time");
  const [offset, setOffset] = useState(0);
  const keywordId = keywords.some((keyword) => String(keyword.id) === selected) ? selected : "";

  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      try {
        setStatus(await api<Status>("/monitor/status", { signal: controller.signal }));
        if (keywordId) {
          const params = new URLSearchParams({ sort, offset: String(offset) });
          if (source) params.set("source", source);
          if (importance) params.set("importance", importance);
          if (minRelevance) params.set("min_relevance", minRelevance);
          if (days) params.set("days", days);
          setItems(await api<Hotspot[]>(`/keywords/${keywordId}/hotspots?${params}`, { signal: controller.signal }));
        }
      } catch (err) { if (!controller.signal.aborted) setError(err instanceof Error ? err.message : "讀取失敗"); }
    }
    void load();
    return () => controller.abort();
  }, [keywordId, refresh, revision, source, importance, minRelevance, days, sort, offset]);

  async function action(path: string, method: string, body?: object) {
    if (busy) return;
    setBusy(true); setError(""); setMessage("");
    try {
      const result = await api<{ new_count?: number; status?: string; ai_error_count?: number }>(path, { method, body: body ? JSON.stringify(body) : undefined }, 190000);
      if (result.new_count !== undefined) setMessage(`檢查完成，新增 ${result.new_count} 篇。${result.status === "partial" ? "部分來源暫時失敗。" : ""}${result.ai_error_count ? ` ${result.ai_error_count} 次 AI 作業失敗，搜尋結果已保存。` : ""}`);
      setRefresh((value) => value + 1); onChanged();
    } catch (err) { setError(err instanceof Error ? err.message : "操作失敗"); }
    finally { setBusy(false); }
  }

  return <section className="card" aria-labelledby="monitor-heading">
    <h2 id="monitor-heading" className="text-xl font-semibold">監控與已保存結果</h2>
    <div className="mt-3 flex flex-wrap items-center gap-3"><p className="text-sm">{status ? `自動監控${status.enabled ? "已啟動" : "已暫停"} · 每 ${status.interval_seconds / 60} 分鐘` : "讀取監控狀態中…"}</p>{status && <button className={buttonClass} disabled={busy} onClick={() => void action("/monitor/config", "PATCH", { enabled: !status.enabled })}>{status.enabled ? "暫停排程" : "啟動排程"}</button>}</div>
    {status?.next_run_at && <p className="mt-2 text-xs text-zinc-500">下次執行：{new Date(status.next_run_at).toLocaleString("zh-TW")} · 自動 AI {status.ai_enabled ? "已啟用" : "未啟用"} · Email {status.email_enabled ? "已啟用" : "未啟用"}</p>}
    <div className="mt-4 flex flex-wrap gap-2"><select aria-label="查看保存結果的關鍵字" value={keywordId} disabled={busy} className={inputClass} onChange={(event) => { setSelected(event.target.value); setItems([]); setOffset(0); setMessage(""); setError(""); }}><option value="">請選擇關鍵字</option>{keywords.map((keyword) => <option key={keyword.id} value={keyword.id}>{keyword.text}</option>)}</select>
      <button disabled={busy || !keywordId} onClick={() => void action(`/keywords/${keywordId}/check`, "POST")} className={buttonClass}>{busy ? "處理中…" : "立即檢查並保存"}</button><button disabled={busy} onClick={() => { setError(""); setRefresh((value) => value + 1); }} className={buttonClass}>重新整理</button>
    </div>
    <div aria-live="polite" className="mt-3">{message && <p>{message}</p>}{error && <p role="alert" className="text-red-600">{error}</p>}</div>
    {keywordId && <>
      <div className="mt-4 flex flex-wrap gap-2">
        <select aria-label="保存結果來源" className={inputClass} value={source} onChange={(event) => { setSource(event.target.value); setOffset(0); }}><option value="">所有來源</option>{Object.entries(sourceNames).map(([key, name]) => <option key={key} value={key}>{name}</option>)}</select>
        <select aria-label="重要程度" className={inputClass} value={importance} onChange={(event) => { setImportance(event.target.value); setOffset(0); }}><option value="">所有重要程度</option>{Object.entries(importanceNames).map(([key, name]) => <option key={key} value={key}>{name}</option>)}</select>
        <select aria-label="最低相關性" className={inputClass} value={minRelevance} onChange={(event) => { setMinRelevance(event.target.value); setOffset(0); }}><option value="">所有相關性</option><option value="50">相關性 ≥50</option><option value="80">相關性 ≥80</option></select>
        <select aria-label="保存結果時間範圍" className={inputClass} value={days} onChange={(event) => { setDays(event.target.value); setOffset(0); }}><option value="">所有時間</option><option value="1">最近 24 小時</option><option value="7">最近 7 天</option><option value="30">最近 30 天</option></select>
        <select aria-label="保存結果排序" className={inputClass} value={sort} onChange={(event) => { setSort(event.target.value); setOffset(0); }}><option value="time">最新發布</option><option value="relevance">AI 相關性</option><option value="score">HN 分數</option></select>
      </div>
      <p className="mt-3 text-xs text-zinc-500">已保存結果 · 第 {Math.floor(offset / 50) + 1} 頁 · {items.length} 篇</p>
      <ul className="mt-3 space-y-3">{items.map((item) => {
        const analysis: AnalysisResponse | null = item.analysis_json ? JSON.parse(item.analysis_json) : null;
        return <li key={item.id} className="rounded-lg border border-zinc-200 p-4"><a href={item.url} target="_blank" rel="noopener noreferrer" className="font-semibold text-blue-700 hover:underline">{item.title}</a><p className="mt-2 text-xs text-zinc-500">{sourceNames[item.source]} · {new Date(item.published_at).toLocaleString("zh-TW")}</p>{item.content && <p className="mt-3 text-sm">{item.content}</p>}
          {analysis ? <div className="mt-3 rounded-lg bg-blue-50 p-3 text-sm"><p>相關性 {analysis.analysis.relevance}/100 · 重要程度：{importanceNames[analysis.analysis.importance]}</p><p className="mt-2">{analysis.analysis.summary}</p><p className="mt-2 text-zinc-600">{analysis.analysis.relevance_reason}</p><p className="mt-2 text-xs">未查證 · 僅依標題與摘要分析</p></div> : <button className={`${buttonClass} mt-3`} disabled={busy} onClick={() => void action(`/hotspots/${item.id}/analyze`, "POST")}>AI 分析並保存</button>}
        </li>;
      })}</ul>
      {!items.length && <p className="mt-4 text-zinc-500">目前沒有符合條件的保存結果。</p>}
      <div className="mt-4 flex gap-2"><button className={buttonClass} disabled={busy || offset === 0} onClick={() => setOffset((value) => Math.max(0, value - 50))}>上一頁</button><button className={buttonClass} disabled={busy || items.length < 50} onClick={() => setOffset((value) => value + 50)}>下一頁</button></div>
    </>}
  </section>;
}
