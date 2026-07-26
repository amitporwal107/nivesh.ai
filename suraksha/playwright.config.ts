import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  reporter: 'list',
  timeout: 30_000,
  use: {
    baseURL: 'http://127.0.0.1:8000',
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: '.venv/bin/python app.py',
    url: 'http://127.0.0.1:8000/api/window',
    reuseExistingServer: true,
    timeout: 30_000,
  },
});
