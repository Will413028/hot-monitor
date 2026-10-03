import { defineConfig } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

const db = path.join(mkdtempSync(path.join(tmpdir(), "hot-monitor-e2e-")), "test.db");
const apiPort = Number(process.env.E2E_API_PORT || 18000);
const apiURL = `http://127.0.0.1:${apiPort}`;
export default defineConfig({
  testDir: "./tests", workers: 1, timeout: 90000,
  use: { baseURL: "http://127.0.0.1:13300", channel: process.env.PLAYWRIGHT_CHANNEL || undefined, trace: "retain-on-failure" },
  webServer: [
    { command: `.venv/bin/uvicorn e2e_app:app --host 127.0.0.1 --port ${apiPort}`, cwd: path.resolve(__dirname, "../backend"), url: `${apiURL}/health`, reuseExistingServer: false,
      env: { HOT_MONITOR_E2E: "1", HOT_MONITOR_DB: db, MONITOR_ENABLED: "false", MONITOR_AI_ENABLED: "false", EMAIL_ENABLED: "false", CORS_ORIGINS: "http://127.0.0.1:13300" } },
    { command: "npm run dev -- --hostname 127.0.0.1 --port 13300", url: "http://127.0.0.1:13300", reuseExistingServer: false, timeout: 300000,
      env: { HOT_MONITOR_E2E: "1", NEXT_PUBLIC_API_BASE_URL: apiURL } },
  ],
});
