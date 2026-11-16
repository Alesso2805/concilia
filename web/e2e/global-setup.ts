import { chromium, FullConfig } from '@playwright/test';

import { credentials, SIGNED_IN } from './fixtures';

// One login for every test that only needs to be signed in: the API allows 10 login attempts
// per email every 15 minutes, and the login specs spend some of them on purpose.
export default async function globalSetup(config: FullConfig): Promise<void> {
  const { baseURL, ignoreHTTPSErrors, locale } = config.projects[0].use;
  const browser = await chromium.launch();
  const page = await browser.newPage({ baseURL, ignoreHTTPSErrors, locale });
  await page.goto('/iniciar-sesion');
  await page.getByLabel('Correo').fill(credentials.email);
  await page.getByLabel('Contraseña').fill(credentials.password);
  await page.getByRole('button', { name: 'Ingresar' }).click();
  await page.waitForURL('/');
  await page.context().storageState({ path: SIGNED_IN });
  await browser.close();
}
