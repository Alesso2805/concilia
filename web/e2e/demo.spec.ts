import { expect, expectAccessible, test } from './fixtures';

test('a visitor enters a demo, reviews its months and switches to the reviewer', async ({
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
  await page.getByRole('option', { name: 'octubre de 2026' }).click();
  await expect(page.getByRole('tab', { name: 'Propuestas (103)' })).toBeVisible();
  await expect(page.getByRole('table')).toContainText('R1');
  await expectAccessible(page);

  const navigation = page.getByRole('navigation', { name: 'Principal' });
  await expect(navigation.getByRole('link', { name: 'Importaciones' })).toBeVisible();
  await page.getByRole('button', { name: 'Ver como: Análisis' }).click();
  await page.getByRole('menuitemradio', { name: 'Revisión' }).click();

  await expect(page.getByRole('button', { name: 'Ver como: Revisión' })).toBeVisible();
  await expect(navigation.getByRole('link', { name: 'Importaciones' })).toBeHidden();
  await expect(page.getByRole('button', { name: 'Correr el motor' })).toBeDisabled();
  await expectAccessible(page);
});
