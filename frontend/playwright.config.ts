import path from "node:path";
import { defineConfig } from "@playwright/test";

// End-to-end tests of the four demo scenarios (docs/day-6-implementation-brief.md section 5).
//
//   * globalSetup runs `scripts/demo_prepare.py --reset`: it reseeds the database (about 6 minutes) and brings the four decisions to
//     their demo state through the real API with the replay client. AI Coach ends at `decided`, so a run cannot be repeated without
//     a reset. Set E2E_SKIP_RESET=1 to skip it ONLY when the database is already freshly prepared.
//   * webServer starts the backend (uvicorn, DDR_LLM_MODE=replay, fixed as-of date) and the built frontend (`next start`).
//   * 127.0.0.1 everywhere: "localhost" can hang on some Windows setups.
const root = path.resolve(__dirname, "..");
const win = process.platform === "win32";
const python = win ? path.join(root, "backend", ".venv", "Scripts", "python.exe") : path.join(root, "backend", ".venv", "bin", "python");
const reuse = process.env.E2E_REUSE_SERVERS === "1";

export default defineConfig({
  testDir: "./e2e",
  // Day 7: the README screenshots run on demand only (SCREENSHOTS=1 runs just that spec).
  ...(process.env.SCREENSHOTS === "1" ? { testMatch: "**/screenshots.spec.ts" } : { testIgnore: "**/screenshots.spec.ts" }),
  timeout: 90_000,
  expect: { timeout: 15_000 },
  workers: 1,
  fullyParallel: false,
  retries: 0,
  reporter: [["list"]],
  globalSetup: "./e2e/global-setup.ts",
  use: {
    baseURL: "http://127.0.0.1:3000",
    headless: true,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
  webServer: [
    {
      command: `"${python}" -m uvicorn app.main:app --host 127.0.0.1 --port 8000`,
      cwd: root,
      url: "http://127.0.0.1:8000/health",
      timeout: 120_000,
      reuseExistingServer: reuse,
      env: { ...(process.env as Record<string, string>), DDR_LLM_MODE: "replay", DDR_AS_OF_DATE: "2026-10-01", PYTHONPATH: `${path.join(root, "backend")}${path.delimiter}${root}` },
    },
    {
      command: "npm run build && npx next start -H 127.0.0.1 -p 3000",
      cwd: __dirname,
      url: "http://127.0.0.1:3000",
      timeout: 240_000,
      reuseExistingServer: reuse,
      env: { ...(process.env as Record<string, string>) },
    },
  ],
});
