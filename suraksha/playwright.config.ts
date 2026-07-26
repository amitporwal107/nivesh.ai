import { defineConfig } from '@playwright/test';

// Point at a deployed instance with SURAKSHA_URL (e.g. a tunnel to the staging VM);
// otherwise the suite boots a local app.py itself.
const remote = process.env.SURAKSHA_URL;

export default defineConfig({
  testDir: './e2e',
  reporter: 'list',
  timeout: 30_000,
  use: {
    baseURL: remote ?? 'http://127.0.0.1:8000',
    screenshot: 'only-on-failure',
  },
  ...(remote ? {} : {
    webServer: {
      command: '.venv/bin/python app.py',
      url: 'http://127.0.0.1:8000/api/window',
      reuseExistingServer: true,
      timeout: 30_000,
    },
  }),
});
