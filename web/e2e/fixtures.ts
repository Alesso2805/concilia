import AxeBuilder from '@axe-core/playwright';
import { Page, expect, test as base } from '@playwright/test';

declare global {
  interface Window {
    cspViolations: string[];
  }
}

function required(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Set ${name} to the email or password of an organization admin`);
  }
  return value;
}

export const SIGNED_IN = 'e2e/.auth/session.json';

export const credentials = {
  email: required('E2E_EMAIL'),
  password: required('E2E_PASSWORD'),
};

// Every test fails if the page reports a Content Security Policy violation.
export const test = base.extend<{ cspGuard: void }>({
  cspGuard: [
    async ({ page }, use) => {
      await page.addInitScript(() => {
        window.cspViolations = [];
        document.addEventListener('securitypolicyviolation', (event) => {
          window.cspViolations.push(`${event.violatedDirective} ${event.blockedURI}`);
        });
      });
      const consoleViolations: string[] = [];
      page.on('console', (message) => {
        if (message.type() === 'error' && message.text().includes('Content Security Policy')) {
          consoleViolations.push(message.text());
        }
      });
      await use();
      const reported = await page.evaluate(() => window.cspViolations ?? []).catch(() => []);
      expect([...reported, ...consoleViolations]).toEqual([]);
    },
    { auto: true },
  ],
});

export { expect };

export async function expectAccessible(page: Page): Promise<void> {
  // Contrast is measured on what is painted, so let dialogs and backdrops finish fading in.
  await page.waitForFunction(() =>
    document
      .getAnimations()
      .every(
        (animation) =>
          animation.playState !== 'running' ||
          animation.effect?.getTiming().iterations === Infinity,
      ),
  );
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze();
  const violations = results.violations.map(
    (violation) =>
      `${violation.id}: ${violation.help} at ${violation.nodes.map((node) => node.target.join(' ')).join(', ')}`,
  );
  expect(violations).toEqual([]);
}

export async function logIn(page: Page, path = '/'): Promise<void> {
  await page.goto(path);
  await page.getByLabel('Correo').fill(credentials.email);
  await page.getByLabel('Contraseña').fill(credentials.password);
  await page.getByRole('button', { name: 'Ingresar' }).click();
  await expect(page).toHaveURL(path);
}

/** Opens the app with the session saved by the global setup (`test.use({ storageState })`). */
export async function openApp(page: Page, path = '/'): Promise<void> {
  await page.goto(path);
  await expect(page).toHaveURL(path);
}

/** Calls the API as the signed-in user of the page, with the CSRF header. */
export async function callApi(
  page: Page,
  method: 'GET' | 'POST' | 'PUT',
  path: string,
  data?: unknown,
): Promise<unknown> {
  const cookies = await page.context().cookies();
  const token = cookies.find((cookie) => cookie.name === '__Host-XSRF-TOKEN')?.value ?? '';
  const response = await page.request.fetch(path, {
    method,
    data,
    headers: { 'X-XSRF-TOKEN': token, Origin: new URL(page.url()).origin },
  });
  expect(response.ok(), `${method} ${path} -> ${response.status()}`).toBe(true);
  return response.status() === 204 ? null : response.json();
}

export function uuidV7(): string {
  const hex = Date.now().toString(16).padStart(12, '0');
  const random = Array.from(crypto.getRandomValues(new Uint8Array(10)), (byte) =>
    byte.toString(16).padStart(2, '0'),
  ).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8)}-7${random.slice(0, 3)}-8${random.slice(3, 6)}-${random.slice(6, 18)}`;
}

/** Uploads and confirms an import through the API, waiting for both jobs. */
export async function importFile(
  page: Page,
  profileId: string,
  name: string,
  content: string,
): Promise<void> {
  const cookies = await page.context().cookies();
  const token = cookies.find((cookie) => cookie.name === '__Host-XSRF-TOKEN')?.value ?? '';
  const response = await page.request.post('/api/app/imports', {
    multipart: {
      id: uuidV7(),
      import_profile_id: profileId,
      file: { name, mimeType: 'text/csv', buffer: Buffer.from(content) },
    },
    headers: { 'X-XSRF-TOKEN': token, Origin: new URL(page.url()).origin },
  });
  expect(response.ok(), `upload ${name} -> ${response.status()}`).toBe(true);
  const fileId = ((await response.json()) as { file: { id: string } }).file.id;
  const status = async () =>
    ((await callApi(page, 'GET', `/api/app/imports/${fileId}`)) as { file: { status: string } })
      .file.status;
  await expect.poll(status).toBe('previewed');
  await callApi(page, 'POST', `/api/app/imports/${fileId}/confirm`);
  await expect.poll(status).toBe('confirmed');
}
