import type { NextConfig } from "next";
const nextConfig: NextConfig = {
  output: "standalone",
  distDir: process.env.HOT_MONITOR_E2E === "1" ? ".next-e2e" : ".next",
};
export default nextConfig;
