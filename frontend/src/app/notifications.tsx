"use client";
import { useEffect, useState } from "react";
import { api, API_BASE, buttonClass } from "./api";

type Notice = { id: number; keyword_id: number; hotspot_id: number; title: string; body: string; is_read: boolean; created_at: string; email_status: string };
const emailLabels: Record<string, string> = { disabled: "未排入 Email", pending: "Email 等待發送", sending: "Email 發送中", sent: "Email 已發送", failed: "Email 發送失敗" };

export default function Notifications({ onNew, revision }: { onNew: () => void; revision: number }) {
  const [items, setItems] = useState<Notice[]>([]);
  const [connection, setConnection] = useState("連線中");
  const [error, setError] = useState("");
  useEffect(() => {
    let disposed = false; let stream: EventSource | null = null;
    api<Notice[]>("/notifications").then((data) => {
      if (disposed) return;
      setItems(data);
      const after = Math.max(0, ...data.map((item) => item.id));
      stream = new EventSource(`${API_BASE}/events?after=${after}`);
      stream.onopen = () => setConnection("即時通知已連線");
      stream.onerror = () => setConnection("重新連線中");
      stream.addEventListener("notification", (event) => {
        const item: Notice = JSON.parse((event as MessageEvent).data);
        setItems((previous) => [item, ...previous.filter((notice) => notice.id !== item.id)].slice(0, 50));
        onNew();
      });
    }).catch((err) => { if (!disposed) { setConnection("連線失敗"); setError(err.message); } });
    return () => { disposed = true; stream?.close(); };
  }, [onNew]);
  useEffect(() => {
    if (!revision) return;
    const controller = new AbortController();
    api<Notice[]>("/notifications", { signal: controller.signal }).then(setItems).catch((err) => { if (!controller.signal.aborted) setError(err.message); });
    return () => controller.abort();
  }, [revision]);
  async function read(id: number) {
    try {
      const updated = await api<Notice>(`/notifications/${id}/read`, { method: "PATCH" });
      setItems((previous) => previous.map((item) => item.id === id ? updated : item));
    } catch (err) { setError(err instanceof Error ? err.message : "更新失敗"); }
  }
  return <section className="card" aria-labelledby="notification-heading"><h2 id="notification-heading" className="text-xl font-semibold">通知中心</h2><p className="mt-2 text-xs text-zinc-500" aria-live="polite">{connection} · 最近 {items.length} 則／未讀 {items.filter((item) => !item.is_read).length} 則</p>{error && <p role="alert" className="mt-2 text-red-600">{error}</p>}
    <ul className="mt-4 max-h-[600px] space-y-3 overflow-auto">{items.map((item) => <li key={item.id} className={`rounded-lg p-3 ${item.is_read ? "bg-zinc-50" : "bg-blue-50"}`}><p className="break-words text-sm font-semibold">{item.title}</p><p className="mt-2 text-xs text-zinc-500">{new Date(item.created_at).toLocaleString("zh-TW")} · {emailLabels[item.email_status]}</p>{!item.is_read && <button className={`${buttonClass} mt-2`} onClick={() => void read(item.id)}>標為已讀</button>}</li>)}</ul>{!items.length && <p className="mt-4 text-sm text-zinc-500">監控發現新文章時會出現在這裡。</p>}
  </section>;
}
