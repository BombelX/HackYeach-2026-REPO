import { defineConfig } from "@playwright/test";
import { fileURLToPath } from "node:url";
const root = fileURLToPath(new URL("..", import.meta.url));

export default defineConfig({
  testDir: "./e2e",
  timeout: 45_000,
  workers: 1,
  fullyParallel: false,
  use: {
    baseURL: "http://localhost:5180",
    channel: "chrome",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    launchOptions: {
      args: [
        "--use-fake-device-for-media-stream",
        "--use-fake-ui-for-media-stream",
      ],
    },
  },
  webServer: [
    {
      command:
        ".venv-bank\\Scripts\\python.exe webrtc_server.py --host 127.0.0.1 --preview-only --no-analysis",
      cwd: root,
      url: "http://127.0.0.1:8080/health",
      reuseExistingServer: !process.env.CI,
    },
    {
      command:
        ".venv-bank\\Scripts\\python.exe bank24_server.py --demo --port 8082 --origin http://localhost:5180 --database data/e2e-bank24.sqlite",
      cwd: root,
      url: "http://127.0.0.1:8082/health",
      reuseExistingServer: false,
    },
    {
      command: "npm run dev -- --port 5180",
      url: "http://localhost:5180",
      env: { BANK24_API_URL: "http://127.0.0.1:8082" },
      reuseExistingServer: false,
    },
  ],
});
