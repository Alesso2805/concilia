import { expect, logIn, test } from './fixtures';

const CONTENT_SECURITY_POLICY =
  "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; " +
  "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; " +
  "frame-ancestors 'none'";

test('pages carry the security headers', async ({ page }) => {
  const response = await page.goto('/iniciar-sesion');
  const headers = response!.headers();

  expect(headers['content-security-policy']).toBe(CONTENT_SECURITY_POLICY);
  expect(headers['strict-transport-security']).toMatch(/^max-age=\d+/);
  expect(headers['referrer-policy']).toBe('no-referrer');
  expect(headers['x-content-type-options']).toBe('nosniff');
  expect(headers['server']).toBeUndefined();
});

test('session cookies are host-only and secure, and only the CSRF one is readable', async ({
  page,
  context,
}) => {
  await logIn(page);

  const cookies = Object.fromEntries((await context.cookies()).map((c) => [c.name, c]));
  const session = cookies['__Host-concilia_session'];
  const xsrf = cookies['__Host-XSRF-TOKEN'];

  expect(session).toMatchObject({ secure: true, httpOnly: true, sameSite: 'Lax', path: '/' });
  expect(xsrf).toMatchObject({ secure: true, httpOnly: false, path: '/' });
});
