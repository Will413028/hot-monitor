export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

export async function api<T>(path: string, options: RequestInit = {}, timeout = 15000): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    cache: "no-store", ...options,
    signal: options.signal ?? AbortSignal.timeout(timeout),
    headers: { "Content-Type": "application/json", ...options.headers },
  });
  if (response.status === 204) return undefined as T;
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail
    : response.status === 502 ? "搜尋來源暫時無法使用，請稍後重試" : `操作失敗（${response.status}）`);
  return data as T;
}

export type Keyword = { id: number; text: string; is_active: boolean; last_checked_at: string | null; last_check_status: string | null };
export type SearchResult = { title: string; url: string; source: string; source_id: string; published_at: string; score: number; comment_count: number; content: string };
export type SourceStatus = { source: string; status: "ok" | "partial" | "error"; count: number; error: string | null };
export type SearchResponse = { results: SearchResult[]; sources: SourceStatus[]; queries: string[] };
export type AnalysisResponse = { analysis: { relevance: number; relevance_reason: string; importance: string; summary: string }; verification: "unverified"; model: string };
export const sourceNames: Record<string, string> = { hackernews: "Hacker News", github_blog: "GitHub Blog", google_news: "Google News" };
export const importanceNames: Record<string, string> = { low: "低", medium: "一般", high: "高", urgent: "緊急" };
export const buttonClass = "shrink-0 whitespace-nowrap rounded-lg border border-zinc-300 px-3 py-2 text-sm font-medium hover:bg-zinc-100 disabled:opacity-40 disabled:cursor-not-allowed";
export const inputClass = "min-w-0 rounded-lg border border-zinc-300 bg-white px-3 py-2";
