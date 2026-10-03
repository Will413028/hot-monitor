"use client";

import { useCallback, useEffect, useState } from "react";
import { api, buttonClass, inputClass, Keyword } from "./api";
import SearchPanel from "./search-panel";
import MonitorPanel from "./monitor-panel";
import Notifications from "./notifications";

export default function Home() {
  const [keywords, setKeywords] = useState<Keyword[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [searchSelection, setSearchSelection] = useState<{ text: string; nonce: number } | null>(null);
  const [health, setHealth] = useState("");
  const refresh = useCallback(() => setRevision((value) => value + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    api<Keyword[]>("/keywords", { signal: controller.signal })
      .then(setKeywords).catch((err) => { if (!controller.signal.aborted) setError(err.message); });
    return () => controller.abort();
  }, [revision]);

  async function mutate(path: string, method: string, body?: object) {
    if (busy) return;
    setBusy(true); setError("");
    try {
      await api(path, { method, body: body ? JSON.stringify(body) : undefined });
      if (method === "POST") setText("");
      setKeywords(await api<Keyword[]>("/keywords"));
      setRevision((value) => value + 1);
    } catch (err) { setError(err instanceof Error ? err.message : "操作失敗"); }
    finally { setBusy(false); }
  }

  return <main className="mx-auto max-w-7xl px-5 py-10">
    <header className="mb-8 flex flex-wrap items-center justify-between gap-4">
      <div><p className="text-sm font-semibold text-blue-600">資訊探索與持續追蹤</p><h1 className="mt-2 text-4xl font-bold tracking-tight">Hot Monitor</h1><p className="mt-3 text-zinc-500">搜尋、分析、保存，讓值得關注的動態自動找上你。</p></div>
      <div><button className={buttonClass} onClick={async () => {
        try { const result = await api<{status: string}>("/health"); setHealth(result.status === "ok" ? "後端連線正常" : "後端狀態異常"); }
        catch { setHealth("無法連線到後端"); }
      }}>檢查後端</button><p aria-live="polite" className="mt-2 text-sm">{health}</p></div>
    </header>
    <div className="grid gap-6 lg:grid-cols-[320px_1fr]">
      <aside className="space-y-6">
        <section className="card" aria-labelledby="keyword-heading">
          <h2 id="keyword-heading" className="text-xl font-semibold">監控關鍵字</h2>
          <form className="mt-4 flex gap-2" onSubmit={(event) => { event.preventDefault(); if (text.trim()) void mutate("/keywords", "POST", { text: text.trim() }); }}>
            <label htmlFor="keyword" className="sr-only">新關鍵字</label><input id="keyword" value={text} maxLength={100} required onChange={(event) => setText(event.target.value)} placeholder="例如：Copilot" className={`${inputClass} w-full`} />
            <button className={buttonClass} disabled={busy || !text.trim()}>新增</button>
          </form>
          {error && <p role="alert" className="mt-3 text-red-600">{error}</p>}
          {!keywords.length && <p className="mt-4 text-sm text-zinc-500">新增關鍵字開始追蹤。</p>}
          <ul className="mt-4 space-y-3">{keywords.map((keyword) => <li key={keyword.id} className="rounded-lg bg-zinc-50 p-3">
            <div className="flex items-center justify-between gap-3"><strong className="break-all">{keyword.text}</strong><span className={`text-xs ${keyword.is_active ? "text-green-700" : "text-zinc-500"}`}>{keyword.is_active ? "已啟用" : "已暫停"}</span></div>
            {keyword.last_checked_at && <p className="mt-2 text-xs text-zinc-500">上次檢查：{new Date(keyword.last_checked_at).toLocaleString("zh-TW")} · {keyword.last_check_status}</p>}
            <div className="mt-3 flex flex-wrap gap-2">
              <button className={buttonClass} onClick={() => setSearchSelection({ text: keyword.text, nonce: Date.now() })}>搜尋</button>
              <button className={buttonClass} disabled={busy} onClick={() => void mutate(`/keywords/${keyword.id}`, "PATCH", { is_active: !keyword.is_active })}>{keyword.is_active ? "暫停" : "啟用"}</button>
              <button className={`${buttonClass} text-red-600`} disabled={busy} onClick={() => { if (window.confirm(`刪除「${keyword.text}」及其保存結果？`)) void mutate(`/keywords/${keyword.id}`, "DELETE"); }}>刪除</button>
            </div>
          </li>)}</ul>
        </section>
        <Notifications onNew={refresh} revision={revision} />
      </aside>
      <div className="space-y-6"><SearchPanel key={searchSelection?.nonce ?? "initial"} initialQuery={searchSelection?.text ?? ""} /><MonitorPanel keywords={keywords} revision={revision} onChanged={refresh} /></div>
    </div>
  </main>;
}
