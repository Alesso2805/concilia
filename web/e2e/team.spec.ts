import { expect, expectAccessible, logIn, test } from './fixtures';

test('an admin invites someone who joins, and then removes them', async ({
  page,
  browser,
  baseURL,
}) => {
  const run = Date.now();
  const email = `invitada-${run}@example.com`;
  const name = `Invitada ${run}`;
  await logIn(page);

  await page
    .getByRole('navigation', { name: 'Principal' })
    .getByRole('link', { name: 'Equipo' })
    .click();
  await expect(page.getByRole('heading', { name: 'Equipo', level: 1 })).toBeVisible();
  await expectAccessible(page);

  await page.getByRole('button', { name: 'Invitar' }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Correo').fill(email);
  await expectAccessible(page);
  await dialog.getByRole('button', { name: 'Crear invitación' }).click();
  const link = await dialog.getByLabel('Enlace de invitación').inputValue();
  expect(link).toMatch(/\/invitacion#.{40,}$/);
  await dialog.getByRole('button', { name: 'Listo' }).click();
  await expect(page.getByRole('table').nth(1)).toContainText(email);

  const invitee = await browser.newContext({
    baseURL,
    ignoreHTTPSErrors: true,
    reducedMotion: 'reduce',
  });
  const inviteePage = await invitee.newPage();
  await inviteePage.goto(link);
  await expect(inviteePage).toHaveURL('/invitacion');
  await expectAccessible(inviteePage);
  await inviteePage.getByLabel('Correo').fill(email);
  await inviteePage.getByLabel('Nombre').fill(name);
  await inviteePage.getByLabel('Contraseña').fill('una clave bastante larga');
  await inviteePage.getByRole('button', { name: 'Crear cuenta y unirme' }).click();
  await expect(inviteePage.getByRole('heading', { name: 'Inicio' })).toBeVisible();
  await expect(inviteePage.getByText('Tus roles: Análisis.')).toBeVisible();
  await expect(inviteePage.getByRole('link', { name: 'Equipo' })).toHaveCount(0);
  await inviteePage.goto('/equipo');
  await expect(inviteePage).toHaveURL('/sin-permiso');

  await page.reload();
  await expect(page.getByRole('table').first()).toContainText(email);
  await page.getByRole('button', { name: `Dar de baja a ${name}` }).click();
  await expectAccessible(page);
  await page.getByRole('dialog').getByRole('button', { name: 'Dar de baja' }).click();
  await expect(page.getByRole('table').first()).not.toContainText(email);

  await inviteePage.reload();
  await expect(inviteePage).toHaveURL(/\/iniciar-sesion/);
  await invitee.close();
});

test('an invitation link without a token is explained', async ({ page }) => {
  await page.goto('/invitacion');

  await expect(page.getByText('Este enlace de invitación no es válido.')).toBeVisible();
  await expectAccessible(page);
});
