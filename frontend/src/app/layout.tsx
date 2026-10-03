import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Hot Monitor",
  description: "熱點監控學習專案",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-Hant" className="h-full antialiased">
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
