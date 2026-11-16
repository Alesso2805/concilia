import { expect, expectAccessible, openApp, SIGNED_IN, test } from './fixtures';

test.use({ storageState: SIGNED_IN });

test('an admin sets up an account, a profile from a template and the tolerances', async ({
  page,
}) => {
  const run = Date.now();
  const alias = `Recaudación ${run}`;
  const profile = `BCP ${run}`;
  await openApp(page);
  const navigation = page.getByRole('navigation', { name: 'Principal' });

  await navigation.getByRole('link', { name: 'Cuentas bancarias' }).click();
  await expect(page.getByRole('heading', { name: 'Cuentas bancarias', level: 1 })).toBeVisible();
  await page.getByRole('button', { name: 'Nueva cuenta' }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByRole('combobox', { name: 'Banco' }).click();
  await page.getByRole('option', { name: 'BCP', exact: true }).click();
  await dialog.getByLabel('Alias').fill(alias);
  await dialog.getByLabel('Últimos 4 dígitos').fill('4521');
  await expectAccessible(page);
  await dialog.getByRole('button', { name: 'Guardar' }).click();
  await expect(page.getByRole('table')).toContainText(alias);
  await expectAccessible(page);

  await navigation.getByRole('link', { name: 'Perfiles de importación' }).click();
  await page.getByRole('link', { name: 'Nuevo perfil' }).click();
  await page.getByRole('combobox', { name: 'Partir de una plantilla' }).click();
  await page.getByRole('option', { name: 'BCP · movimientos en Excel' }).click();
  await expect(page.getByRole('status')).toContainText('verifica los nombres de columna');
  await page.getByRole('combobox', { name: 'Cuenta bancaria' }).click();
  await page.getByRole('option', { name: new RegExp(alias) }).click();
  await page.getByLabel('Nombre del perfil').fill(profile);
  await expect(page.getByLabel('Monto con signo')).toHaveValue('Monto');
  await expectAccessible(page);
  await page.getByRole('button', { name: 'Guardar perfil' }).click();
  await expect(page).toHaveURL('/perfiles');
  await expect(page.getByRole('table')).toContainText(`${profile}Extracto bancario${alias}`);
  await expectAccessible(page);

  await navigation.getByRole('link', { name: 'Configuración' }).click();
  await page.getByLabel('Tolerancia sobre el saldo (%)').fill('0.25');
  await expectAccessible(page);
  await page.getByRole('button', { name: 'Guardar' }).click();
  await expect(page.getByText('Configuración guardada.')).toBeVisible();
  await page.reload();
  await expect(page.getByLabel('Tolerancia sobre el saldo (%)')).toHaveValue('0.25');
  await page.getByLabel('Tolerancia sobre el saldo (%)').fill('0.5');
  await page.getByRole('button', { name: 'Guardar' }).click();
  await expect(page.getByText('Configuración guardada.').first()).toBeVisible();
});
