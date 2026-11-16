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
  await page.locator('input[type="file"]').setInputFiles({
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

test('an analyst imports receivables and previews what a second file changes', async ({ page }) => {
  const run = Date.now();
  const series = `E${String(run % 1000).padStart(3, '0')}`;
  const number = Math.floor(run / 1000) % 10_000_000;
  const [first, second] = [`${series}-${number}`, `${series}-${number + 1}`];
  await logIn(page);
  const session = (await callApi(page, 'GET', '/api/app/session')) as { user_id: string };
  await callApi(page, 'PUT', `/api/app/team/members/${session.user_id}/roles`, {
    roles: ['admin', 'analyst'],
  });
  await callApi(page, 'POST', '/api/app/import-profiles', {
    id: UUID_V7(),
    kind: 'receivables',
    name: `Cobros ${run}`,
    config: {
      format: 'csv',
      delimiter: ';',
      date_format: 'DD/MM/YYYY',
      decimal_separator: ',',
      thousands_separator: '.',
      columns: {
        customer_name: 'Cliente',
        customer_tax_id: 'RUC',
        doc_number: 'Documento',
        issued_on: 'Emision',
        due_on: 'Vencimiento',
        amount: 'Monto',
      },
    },
  });
  const header = 'Cliente;RUC;Documento;Emision;Vencimiento;Monto';
  const january = [
    header,
    `Comercial Andina SAC;20512345678;${first};02/01/2027;31/01/2027;1.180,00`,
    `Gloria SA;;${second};03/01/2027;15/02/2027;500,00`,
    'Sin Documento SAC;;;03/01/2027;15/02/2027;10,00',
  ].join('\n');
  const february = [
    header,
    `Comercial Andina SAC;20512345678;${first};02/01/2027;28/02/2027;1.200,00`,
    `Gloria SA;;${second};03/01/2027;15/02/2027;500,00`,
  ].join('\n');

  async function uploadReceivables(name: string, content: string): Promise<void> {
    await page.goto('/importaciones');
    await page.getByText('Perfil de importación', { exact: true }).click();
    await page.getByRole('option', { name: `Cobros ${run}` }).click();
    await page.locator('input[type="file"]').setInputFiles({
      name,
      mimeType: 'text/csv',
      buffer: Buffer.from(content),
    });
    await page.getByRole('button', { name: 'Subir y revisar' }).click();
    await expect(page.getByRole('heading', { name })).toBeVisible();
  }

  await uploadReceivables(`cobros-enero-${run}.csv`, january);
  await expect(page.getByRole('tab', { name: 'Nuevos o con cambios (2)' })).toBeVisible();
  await expect(page.getByRole('table')).toContainText('Comercial Andina SAC');
  await expectAccessible(page);
  await page.getByRole('tab', { name: 'Con errores (1)' }).click();
  await expect(page.getByRole('table')).toContainText('Falta el número de documento');
  await page.getByRole('button', { name: 'Confirmar 2 cobros' }).click();
  await expect(page.getByText('Sus cobros ya están disponibles para conciliar.')).toBeVisible();

  await uploadReceivables(`cobros-febrero-${run}.csv`, february);
  await expect(page.getByRole('tab', { name: 'Nuevos o con cambios (1)' })).toBeVisible();
  await expect(page.getByRole('table')).toContainText('Antes: vence 31/01/2027, S/ 1,180.00');
  await page.getByRole('tab', { name: 'Sin cambios (1)' }).click();
  await expect(page.getByRole('table')).toContainText('Gloria SA');
  await expectAccessible(page);
  await page.getByRole('button', { name: 'Descartar' }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Descartar' }).click();
  await expect(page.getByText('no se guardó ningún cobro')).toBeVisible();
});
