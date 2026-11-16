import { callApi, expect, expectAccessible, logIn, test } from './fixtures';

const UUID_V7 = () => {
  const hex = Date.now().toString(16).padStart(12, '0');
  const random = Array.from(crypto.getRandomValues(new Uint8Array(10)), (byte) =>
    byte.toString(16).padStart(2, '0'),
  ).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8)}-7${random.slice(0, 3)}-8${random.slice(3, 6)}-${random.slice(6, 18)}`;
};

test('an analyst uploads a statement, confirms it and voids it', async ({ page }) => {
  const run = Date.now();
  await logIn(page);
  const session = (await callApi(page, 'GET', '/api/app/session')) as { user_id: string };
  await callApi(page, 'PUT', `/api/app/team/members/${session.user_id}/roles`, {
    roles: ['admin', 'analyst'],
  });
  const account = (await callApi(page, 'POST', '/api/app/bank-accounts', {
    id: UUID_V7(),
    bank: 'BCP',
    alias: `Importación ${run}`,
    number_last4: '7777',
  })) as { id: string };
  await callApi(page, 'POST', '/api/app/import-profiles', {
    id: UUID_V7(),
    kind: 'bank_statement',
    bank_account_id: account.id,
    name: `CSV ${run}`,
    config: {
      format: 'csv',
      delimiter: ';',
      date_format: 'DD/MM/YYYY',
      decimal_separator: ',',
      thousands_separator: '.',
      columns: { date: 'Fecha', description: 'Detalle', amount: 'Importe' },
    },
  });
  const statement = [
    'Fecha;Detalle;Importe',
    `05/01/2027;PAGO FACT F001-${run % 100000};1.180,00`,
    '06/01/2027;COMISION;-12,50',
    '08/01/2027;SIN MONTO;',
  ].join('\n');

  await page.goto('/importaciones');
  await expect(page.getByRole('heading', { name: 'Importaciones', level: 1 })).toBeVisible();
  await page.getByText('Perfil de importación', { exact: true }).click();
  await page.getByRole('option', { name: `CSV ${run}` }).click();
  await page
    .locator('input[type="file"]')
    .setInputFiles({
      name: `enero-${run}.csv`,
      mimeType: 'text/csv',
      buffer: Buffer.from(statement),
    });
  await expectAccessible(page);
  await page.getByRole('button', { name: 'Subir y revisar' }).click();

  await expect(page.getByRole('heading', { name: `enero-${run}.csv` })).toBeVisible();
  await expect(page.getByRole('tab', { name: 'Válidas (2)' })).toBeVisible();
  await expect(page.getByRole('table')).toContainText('S/ 1,180.00');
  await expectAccessible(page);
  await page.getByRole('tab', { name: 'Con errores (1)' }).click();
  await expect(page.getByRole('table')).toContainText('Falta el monto');

  await page.getByRole('button', { name: 'Confirmar 2 movimientos' }).click();
  await expect(page.getByText('Importación confirmada')).toBeVisible();
  await expectAccessible(page);

  await page.getByRole('button', { name: 'Anular importación' }).click();
  await page.getByRole('dialog').getByLabel('Motivo').fill('Prueba de extremo a extremo');
  await expectAccessible(page);
  await page.getByRole('dialog').getByRole('button', { name: 'Anular importación' }).click();
  await expect(page.getByText('Esta importación se anuló')).toBeVisible();

  await page.goto('/importaciones');
  await expect(page.getByRole('table')).toContainText(`enero-${run}.csv`);
  await expectAccessible(page);
});
