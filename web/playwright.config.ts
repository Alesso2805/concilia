import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  globalSetup: './e2e/global-setup.ts',
  // Each spec is a whole user flow through the real stack; parallel workers slow it down.
  timeout: 60_000,
  forbidOnly: Boolean(process.env['CI']),
  reporter: process.env['CI'] ? [['github'], ['list']] : 'list',
  use: {
    baseURL: process.env['E2E_BASE_URL'] ?? 'https://localhost',
    ignoreHTTPSErrors: true,
    contextOptions: { reducedMotion: 'reduce' },
    locale: 'es-PE',
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
