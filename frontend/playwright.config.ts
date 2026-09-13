import { defineConfig } from "@playwright/test";

// The suite runs against the production build (vite preview) and the real API in
// presentation mode, so every screenshot it writes is pseudonymised.
const python =
  process.env.SENTINEL_PYTHON ?? (process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python");

export default defineConfig({
  testDir: "e2e",
  timeout: 180_000,
  expect: { timeout: 30_000 },
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.SENTINEL_WEB ?? "http://127.0.0.1:4173",
    viewport: { width: 1920, height: 1080 },
    // Uses the installed Chrome, so no browser download is needed.
    channel: process.env.PW_CHANNEL ?? "chrome",
    colorScheme: "dark",
    locale: "en-IN",
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: `${python} -m uvicorn backend.app.main:app --port 8000 --log-level warning`,
      cwd: "..",
      url: "http://127.0.0.1:8000/api/health",
      reuseExistingServer: true,
      timeout: 180_000,
      env: { PRESENTATION_MODE: "1", SCHEDULER_ENABLED: "0" },
    },
    {
      command: "npm run build && npm run preview",
      url: "http://127.0.0.1:4173",
      reuseExistingServer: true,
      timeout: 300_000,
    },
  ],
});
