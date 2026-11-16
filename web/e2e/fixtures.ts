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
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze();
  expect(results.violations.map((violation) => `${violation.id}: ${violation.help}`)).toEqual([]);
}

export async function logIn(page: Page, path = '/'): Promise<void> {
  await page.goto(path);
  await page.getByLabel('Correo').fill(credentials.email);
  await page.getByLabel('Contraseña').fill(credentials.password);
  await page.getByRole('button', { name: 'Ingresar' }).click();
  await expect(page).toHaveURL(path);
}
