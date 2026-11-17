import { credentials, expect, expectAccessible, logIn, test } from './fixtures';

test('a visitor lands on an accessible login that remembers the way back', async ({ page }) => {
  await page.goto('/sin-permiso');

  await expect(page).toHaveURL('/iniciar-sesion?volver=%2Fsin-permiso');
  await expect(page.getByRole('heading', { name: 'Concilia' })).toBeVisible();
  await expectAccessible(page);
});

test('the login stays accessible in the dark scheme', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'dark' });
  await page.goto('/iniciar-sesion');

  await expect(page.getByRole('heading', { name: 'Concilia' })).toBeVisible();
  await expectAccessible(page);
});

test('wrong credentials are explained', async ({ page }) => {
  await page.goto('/iniciar-sesion');
  await page.getByLabel('Correo').fill(credentials.email);
  await page.getByLabel('Contraseña').fill('not the password');
  await page.getByRole('button', { name: 'Ingresar' }).click();

  await expect(page.getByRole('alert')).toHaveText('El correo o la contraseña no son correctos.');
  await expectAccessible(page);
});

test('a member logs in, uses the shell and logs out', async ({ page }) => {
  await logIn(page);

  await expect(page.getByRole('heading', { name: 'Inicio' })).toBeVisible();
  await expect(page.getByRole('navigation', { name: 'Principal' })).toContainText('Inicio');
  await expectAccessible(page);

  await page.getByRole('button', { name: 'Cuenta' }).click();
  const logout = page.waitForResponse('**/api/app/logout');
  await page.getByRole('menuitem', { name: 'Cerrar sesión' }).click();
  expect((await logout).status()).toBe(204);
  await expect(page).toHaveURL('/iniciar-sesion');

  await page.goto('/');
  await expect(page).toHaveURL('/iniciar-sesion?volver=%2F');
});

test('unknown pages inside the app are reported', async ({ page }) => {
  await logIn(page);

  await page.goto('/no-existe');

  await expect(page.getByRole('heading', { name: 'No encontramos esta página' })).toBeVisible();
  await expectAccessible(page);
});

test('the dark theme is applied and stays accessible', async ({ page }) => {
  await logIn(page);

  await page.getByRole('button', { name: 'Cambiar el tema' }).click();
  await page.getByRole('menuitemradio', { name: 'Oscuro' }).click();

  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await expectAccessible(page);
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
});
