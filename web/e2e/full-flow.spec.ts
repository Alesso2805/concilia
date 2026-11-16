import type { Page } from '@playwright/test';

import { expect, expectAccessible, test } from './fixtures';

const navigate = (page: Page, name: string) =>
  page.getByRole('navigation', { name: 'Principal' }).getByRole('link', { name }).click();

async function importDemoFile(page: Page, link: string, profile: string): Promise<void> {
  await navigate(page, 'Importaciones');
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('link', { name: link }).click(),
  ]);
  await page.getByText('Perfil de importación', { exact: true }).click();
  await page.getByRole('option', { name: profile }).click();
  await page.locator('input[type="file"]').setInputFiles(await download.path());
  await page.getByRole('button', { name: 'Subir y revisar' }).click();
  await page.getByRole('button', { name: /^Confirmar \d+ / }).click();
  await expect(page.getByText(/Importación confirmada/)).toBeVisible({ timeout: 20_000 });
}

test('an analyst and a reviewer reconcile a month end to end', async ({ page }) => {
  // The whole monthly cycle with two demo users, through the worker's queue at each step.
  test.slow();
  await page.goto('/demo');
  await expect(page).toHaveURL('/bandeja');

  await importDemoFile(page, 'Extracto de diciembre (CSV)', 'Extracto de la demo (CSV)');
  await importDemoFile(page, 'Cobros de diciembre (CSV)', 'Cobros de la demo (CSV)');
  await expectAccessible(page);

  await navigate(page, 'Bandeja');
  await expect(page.getByRole('combobox', { name: 'Mes' })).toContainText('diciembre de 2026');
  await page.getByRole('button', { name: 'Correr el motor' }).click();
  await expect(page.getByText(/El motor propuso \d+ coincidencias\./)).toBeVisible({
    timeout: 30_000,
  });
  await page.getByRole('button', { name: 'Confirmar todas las de puntaje 100' }).click();
  await expect(page.getByText(/^Se confirmaron? \d+ coincidencias?\./)).toBeVisible();
  await expectAccessible(page);

  await page.getByRole('tab', { name: /^Libres/ }).click();
  await page
    .getByRole('button', { name: /^Pedir ayuda a la IA para / })
    .first()
    .click();
  const ai = page.getByRole('dialog', { name: 'Sugerencias de la IA' });
  await expect(
    ai.getByText(/Sugerencia 1, confianza|Sin sugerencias en la demo/).first(),
  ).toBeVisible({ timeout: 20_000 });
  await ai.getByRole('button', { name: 'Cerrar' }).click();

  await page.getByRole('button', { name: 'Ver como: Análisis' }).click();
  await page.getByRole('menuitemradio', { name: 'Revisión' }).click();
  await expect(page.getByRole('button', { name: 'Ver como: Revisión' })).toBeVisible();
  await page.getByRole('tab', { name: /^Confirmadas/ }).click();
  await page.getByRole('button', { name: 'Aprobar todas las de puntaje 100' }).click();
  await expect(page.getByText(/^Se aprobaron? \d+ coincidencias?\./)).toBeVisible();
  await expectAccessible(page);

  await navigate(page, 'Panel');
  await expect(page.getByRole('combobox', { name: 'Mes' })).toContainText('diciembre de 2026');
  await expect(page.getByText('Conciliado por monto')).toBeVisible();
  await page.getByRole('button', { name: 'Exportar a Excel' }).click();
  const file = page.getByRole('link', { name: 'Descargar conciliacion-2026-12.xlsx' });
  await expect(file).toBeVisible({ timeout: 20_000 });
  const [workbook] = await Promise.all([page.waitForEvent('download'), file.click()]);
  expect(workbook.suggestedFilename()).toBe('conciliacion-2026-12.xlsx');
  await expectAccessible(page);

  await navigate(page, 'Auditoría');
  await page.getByRole('combobox', { name: 'Acción' }).click();
  await page.getByRole('option', { name: 'Aprobó una coincidencia' }).click();
  await page.getByRole('button', { name: 'Filtrar' }).click();
  const events = page.getByRole('region', { name: 'Eventos de auditoría' });
  await expect(events.getByRole('cell', { name: 'Aprobó una coincidencia' }).first()).toBeVisible();
  await expect(events.getByRole('cell', { name: 'Revisora de la demo' }).first()).toBeVisible();
  await expectAccessible(page);
});
