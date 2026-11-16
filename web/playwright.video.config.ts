import { defineConfig } from '@playwright/test';

import base from './playwright.config';

// `npm run e2e:video`: records the end-to-end story slowly enough to follow, as raw material
// for the project's walkthrough video (saved under test-results/).
export default defineConfig({
  ...base,
  timeout: 10 * 60_000,
  use: {
    ...base.use,
    video: { mode: 'on', size: { width: 1280, height: 800 } },
    viewport: { width: 1280, height: 800 },
    launchOptions: { slowMo: 350 },
  },
});
