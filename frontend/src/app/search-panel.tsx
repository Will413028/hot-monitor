"use client";
import { useState } from "react";
import { api, AnalysisResponse, buttonClass, importanceNames, inputClass, SearchResponse, SearchResult, sourceNames } from "./api";

export default function SearchPanel({ initialQuery }: { initialQuery: string }) {
  const [query, setQuery] = useState(initialQuery);
  const [sources, setSources] = useState(Object.keys(sourceNames));
  const [days, setDays] = useState(7);
  const [busy, setBusy] = useState(false);
  const [searched, setSearched] = useState("");
  const [data, setData] = useState<SearchResponse | null>(null);
  const [error, setError] = useState("");
  const [analyses, setAnalyses] = useState<Record<string, AnalysisResponse>>({});
  const [analyzing, setAnalyzing] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [sort, setSort] = useState("time");

  async function search(expanded: boolean) {
    if (busy || analyzing || !query.trim() || !sources.length) return;
    setBusy(true); setError(""); setData(null); setAnalyses({}); setSearched(query.trim());
    const params = new URLSearchParams({ q: query.trim(), days: String(days) });
    sources.forEach((source) => params.append("sources", source));
    try { setData(await api<SearchResponse>(`/search/${expanded ? "expanded" : "all"}?${params}`, {}, expanded ? 50000 : 15000)); }
    catch (err) { setError(err instanceof Error ? err.message : "搜尋失敗"); }
    finally { setBusy(false); }
  }

  async function analyze(item: SearchResult) {
    if (analyzing) return;
    const key = `${item.source}:${item.source_id}`;
    setAnalyzing(key); setError("");
    try {
      const result = await api<AnalysisResponse>("/analyze", { method: "POST", body: JSON.stringify({ keyword: searched, title: item.title.slice(0, 500), content: item.content.slice(0, 2000) }) }, 35000);
      setAnalyses((previous) => ({ ...previous, [key]: result }));
    } catch (err) { setError(err instanceof Error ? err.message : "分析失敗"); }
    finally { setAnalyzing(null); }
  }

  const items = (data?.results ?? []).filter((item) => !filter || item.source === filter).toSorted((a, b) => {
    if (sort === "score") return b.score - a.score;
    if (sort === "relevance") return (analyses[`${b.source}:${b.source_id}`]?.analysis.relevance ?? -1) - (analyses[`${a.source}:${a.source_id}`]?.analysis.relevance ?? -1);
    return Date.parse(b.published_at) - Date.parse(a.published_at);
  });
  return <section className="card" aria-labelledby="search-heading">
    <h2 id="search-heading" className="text-xl font-semibold">多來源與全網新聞搜尋</h2>
    <form className="mt-4 flex flex-wrap gap-2" onSubmit={(event) => { event.preventDefault(); void search(false); }}>
      <label htmlFor="search-query" className="sr-only">搜尋內容</label><input id="search-query" value={query} disabled={busy || !!analyzing} onChange={(event) => setQuery(event.target.value)} maxLength={100} placeholder="輸入想關注的主題" className={`${inputClass} flex-1`} required />
      <select aria-label="搜尋時間範圍" value={days} disabled={busy || !!analyzing} onChange={(event) => setDays(Number(event.target.value))} className={inputClass}><option value={1}>最近 24 小時</option><option value={7}>最近 7 天</option><option value={30}>最近 30 天</option></select>
      <button className={buttonClass} disabled={busy || !!analyzing || !sources.length}>搜尋</button><button type="button" className={buttonClass} disabled={busy || !!analyzing || !query.trim() || !sources.length} onClick={() => void search(true)}>AI 擴展搜尋</button>
    </form>
    <fieldset className="mt-3 flex flex-wrap gap-4"><legend className="sr-only">資訊來源</legend>{Object.entries(sourceNames).map(([key, name]) => <label key={key} className="flex gap-2 text-sm"><input type="checkbox" disabled={busy || !!analyzing} checked={sources.includes(key)} onChange={() => setSources((previous) => previous.includes(key) ? previous.filter((source) => source !== key) : [...previous, key])} />{name}</label>)}</fieldset>
    <p className="mt-3 text-xs text-zinc-500">GitHub Blog 比對最新 RSS 的標題／摘要；Google News 搜尋新聞索引。</p>
    <div aria-live="polite" className="mt-4">{busy && <p>正在搜尋「{searched}」…</p>}{error && <p role="alert" className="text-red-600">{error}</p>}{data && <p>「{searched}」共 {data.results.length} 筆 · 實際搜尋詞：{data.queries.join("、")}</p>}</div>
    {data && <>
      <ul className="mt-2 text-sm text-zinc-500">{data.sources.map((source) => <li key={source.source}>{sourceNames[source.source]}：{source.status === "error" ? "暫時無法使用" : `${source.count} 筆（去重前）${source.status === "partial" ? `，${source.error}` : ""}`}</li>)}</ul>
      <div className="mt-4 flex flex-wrap gap-2"><select className={inputClass} aria-label="搜尋結果來源" value={filter} onChange={(event) => setFilter(event.target.value)}><option value="">所有來源</option>{Object.entries(sourceNames).map(([key, name]) => <option key={key} value={key}>{name}</option>)}</select><select aria-label="搜尋結果排序" className={inputClass} value={sort} onChange={(event) => setSort(event.target.value)}><option value="time">最新發布</option><option value="score">HN 分數</option><option value="relevance">AI 相關性</option></select></div>
      <ul className="mt-4 space-y-3">{items.map((item) => {
        const key = `${item.source}:${item.source_id}`; const analysis = analyses[key]?.analysis;
        return <li key={key} className="rounded-lg border border-zinc-200 p-4"><a href={item.url} target="_blank" rel="noopener noreferrer" className="font-semibold text-blue-700 hover:underline">{item.title}</a>
          <p className="mt-2 text-xs text-zinc-500">{sourceNames[item.source]} · {new Date(item.published_at).toLocaleString("zh-TW")}{item.source === "hackernews" ? ` · ${item.score} 分 · ${item.comment_count} 則留言` : ""}</p>
          {item.content && <p className="mt-3 text-sm">{item.content}</p>}
          <button className={`${buttonClass} mt-3`} disabled={!!analyzing || !!analysis} onClick={() => void analyze(item)}>{analyzing === key ? "分析中…" : analysis ? "已分析" : "AI 分析"}</button>
          {analysis && <div className="mt-3 rounded-lg bg-blue-50 p-3 text-sm"><p>相關性 {analysis.relevance}/100 · 重要程度：{importanceNames[analysis.importance]}</p><p className="mt-2">{analysis.summary}</p><p className="mt-2 text-zinc-600">理由：{analysis.relevance_reason}</p><p className="mt-2 text-xs">未查證 · 僅依標題與摘要分析</p></div>}
        </li>;
      })}</ul>
    </>}
  </section>;
}
