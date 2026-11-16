import { expect, expectAccessible, openApp, SIGNED_IN, test } from './fixtures';

test.use({ storageState: SIGNED_IN });

test('a member reads the audit log and filters it by action', async ({ page }) => {
  await openApp(page, '/auditoria');
  await expect(page.getByRole('heading', { name: 'Auditoría', level: 1 })).toBeVisible();
  const events = page.getByRole('region', { name: 'Eventos de auditoría' });
  await expect(events.getByRole('row').nth(1)).toBeVisible();
  await expectAccessible(page);

  await page.getByRole('combobox', { name: 'Acción' }).click();
  await page.getByRole('option', { name: 'Creó la organización' }).click();
  await page.getByRole('button', { name: 'Filtrar' }).click();

  await expect(events.getByRole('row')).toHaveCount(2);
  await expect(events.getByRole('cell', { name: 'Creó la organización' })).toBeVisible();
  await expect(events.getByRole('cell', { name: 'Origen: consola' })).toBeVisible();
  await expectAccessible(page);

  await page.getByRole('button', { name: 'Quitar filtros' }).click();
  await expect(events.getByRole('row').nth(2)).toBeVisible();
});
