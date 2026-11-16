import { expect, expectAccessible, test } from './fixtures';

test('a visitor enters a demo, reviews its months and the reviewer reopens and closes one', async ({
  page,
}) => {
  await page.goto('/iniciar-sesion');
  await expectAccessible(page);
  await page.getByRole('button', { name: 'Probar la demo' }).click();

  await expect(page).toHaveURL('/bandeja');
  await expect(
    page.getByRole('heading', { name: 'Bandeja de conciliación', level: 1 }),
  ).toBeVisible();
  await expect(page.getByText('Demo', { exact: true })).toBeVisible();
  await expect(page.getByRole('tab', { name: 'Libres (118)' })).toBeVisible();
  await page.getByText('Mes', { exact: true }).click();
  await page.getByRole('option', { name: 'octubre de 2026 (cerrado)' }).click();
  await expect(page.getByText('Este mes está cerrado: solo se puede consultar.')).toBeVisible();
  await expect(page.getByRole('tab', { name: 'Aprobadas (103)' })).toBeVisible();
  await expect(page.getByRole('tab', { name: 'Propuestas (0)' })).toBeVisible();
  await expectAccessible(page);

  const navigation = page.getByRole('navigation', { name: 'Principal' });
  await expect(navigation.getByRole('link', { name: 'Importaciones' })).toBeVisible();
  await page.getByRole('button', { name: 'Ver como: Análisis' }).click();
  await page.getByRole('menuitemradio', { name: 'Revisión' }).click();

  await expect(page.getByRole('button', { name: 'Ver como: Revisión' })).toBeVisible();
  await expect(navigation.getByRole('link', { name: 'Importaciones' })).toBeHidden();
  await expect(page.getByRole('button', { name: 'Correr el motor' })).toBeDisabled();
  await expectAccessible(page);

  await page.getByText('Mes', { exact: true }).click();
  await page.getByRole('option', { name: 'octubre de 2026 (cerrado)' }).click();
  await page.getByRole('button', { name: 'Reabrir mes' }).click();
  const dialog = page.getByRole('dialog', { name: 'Reabrir octubre de 2026' });
  await dialog.getByRole('button', { name: 'Reabrir' }).click();
  await expect(dialog.getByText('Indica el motivo.')).toBeVisible();
  await expectAccessible(page);
  await dialog.getByLabel('Motivo').fill('Faltó registrar una comisión');
  await dialog.getByRole('button', { name: 'Reabrir' }).click();
  await expect(page.getByText('Reabriste octubre de 2026.')).toBeVisible();
  await expect(page.getByText('Este mes está cerrado: solo se puede consultar.')).toBeHidden();

  await page.getByRole('button', { name: 'Cerrar mes' }).click();
  await expect(page.getByText('Cerraste octubre de 2026.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Reabrir mes' })).toBeVisible();
});

test('a visitor imports the third month of the demo from its sample files', async ({ page }) => {
  await page.goto('/demo');
  await expect(page).toHaveURL('/bandeja');
  await page
    .getByRole('navigation', { name: 'Principal' })
    .getByRole('link', { name: 'Importaciones' })
    .click();
  await expect(
    page.getByRole('heading', { name: 'Archivos de ejemplo para la demo' }),
  ).toBeVisible();
  await expectAccessible(page);

  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('link', { name: 'Extracto de diciembre (CSV)' }).click(),
  ]);
  expect(download.suggestedFilename()).toBe('extracto-2026-12.csv');
  await page.getByText('Perfil de importación', { exact: true }).click();
  await page.getByRole('option', { name: 'Extracto de la demo (CSV)' }).click();
  await page.locator('input[type="file"]').setInputFiles(await download.path());
  await page.getByRole('button', { name: 'Subir y revisar' }).click();

  await expect(page.getByRole('tab', { name: 'Ya importadas (3)' })).toBeVisible();
  await expect(page.getByRole('tab', { name: 'Válidas (165)' })).toBeVisible();
  await page.getByRole('button', { name: 'Confirmar 165 movimientos' }).click();
  await expect(page.getByText('Importación confirmada')).toBeVisible();
});

test('the analyst confirms a proposal and the reviewer approves it', async ({ page }) => {
  await page.goto('/demo');
  await expect(page.getByRole('tab', { name: 'Libres (118)' })).toBeVisible();
  await page.getByRole('button', { name: 'Correr el motor' }).click();
  // The run goes through the worker's queue and the 2-second job polling.
  await expect(page.getByText(/El motor propuso \d+ coincidencias\./)).toBeVisible({
    timeout: 20_000,
  });

  await page
    .getByRole('button', { name: /^Ver detalle de / })
    .first()
    .click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('button', { name: 'Confirmar' })).toBeVisible();
  await expectAccessible(page);
  await dialog.getByRole('button', { name: 'Confirmar' }).click();
  await expect(page.getByRole('tab', { name: 'Confirmadas (1)' })).toBeVisible();

  await page.getByRole('button', { name: 'Ver como: Análisis' }).click();
  await page.getByRole('menuitemradio', { name: 'Revisión' }).click();
  await expect(page.getByRole('button', { name: 'Ver como: Revisión' })).toBeVisible();
  await page.getByRole('tab', { name: 'Confirmadas (1)' }).click();
  await page
    .getByRole('button', { name: /^Ver detalle de / })
    .first()
    .click();
  await expect(dialog.getByText('Confirmó')).toBeVisible();
  await expectAccessible(page);
  await dialog.getByRole('button', { name: 'Aprobar' }).click();
  await expect(page.getByRole('tab', { name: 'Aprobadas (1)' })).toBeVisible();
});
