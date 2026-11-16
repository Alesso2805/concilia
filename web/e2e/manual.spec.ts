import {
  callApi,
  expect,
  expectAccessible,
  importFile,
  openApp,
  SIGNED_IN,
  test,
  uuidV7,
} from './fixtures';

test.use({ storageState: SIGNED_IN });

const CSV = {
  format: 'csv',
  delimiter: ';',
  date_format: 'DD/MM/YYYY',
  decimal_separator: ',',
  thousands_separator: '.',
};

test('an analyst reconciles a partial payment by hand', async ({ page }) => {
  const run = Date.now();
  const document = `M${String(run % 1000).padStart(3, '0')}-${Math.floor(run / 1000) % 10_000_000}`;
  await openApp(page);
  const session = (await callApi(page, 'GET', '/api/app/session')) as { user_id: string };
  await callApi(page, 'PUT', `/api/app/team/members/${session.user_id}/roles`, {
    roles: ['admin', 'analyst'],
  });
  const account = (await callApi(page, 'POST', '/api/app/bank-accounts', {
    id: uuidV7(),
    bank: 'BCP',
    alias: `Manual ${run}`,
    number_last4: '5555',
  })) as { id: string };
  const statement = (await callApi(page, 'POST', '/api/app/import-profiles', {
    id: uuidV7(),
    kind: 'bank_statement',
    bank_account_id: account.id,
    name: `Extracto manual ${run}`,
    config: { ...CSV, columns: { date: 'Fecha', description: 'Detalle', amount: 'Importe' } },
  })) as { id: string };
  const receivables = (await callApi(page, 'POST', '/api/app/import-profiles', {
    id: uuidV7(),
    kind: 'receivables',
    name: `Cobros manual ${run}`,
    config: {
      ...CSV,
      columns: {
        customer_name: 'Cliente',
        doc_number: 'Documento',
        issued_on: 'Emision',
        due_on: 'Vencimiento',
        amount: 'Monto',
      },
    },
  })) as { id: string };
  await importFile(
    page,
    statement.id,
    `manual-${run}.csv`,
    ['Fecha;Detalle;Importe', `12/01/2027;PAGO A CUENTA ${document};400,00`].join('\n'),
  );
  await importFile(
    page,
    receivables.id,
    `cobros-manual-${run}.csv`,
    [
      'Cliente;Documento;Emision;Vencimiento;Monto',
      `Comercial Andina SAC;${document};02/01/2027;31/01/2027;1.000,00`,
    ].join('\n'),
  );

  await page.goto(`/bandeja?cuenta=${account.id}&mes=2027-01-01`);
  await expect(page.getByRole('tab', { name: 'Libres (1)' })).toBeVisible();
  await page.getByRole('link', { name: 'Conciliar a mano' }).click();
  await expect(page.getByRole('heading', { name: /Conciliar a mano/, level: 1 })).toBeVisible();
  await page.getByRole('checkbox', { name: `Elegir el abono PAGO A CUENTA ${document}` }).check();
  await page.getByLabel('Documento, cliente o RUC').fill(document);
  await page.getByRole('button', { name: 'Buscar' }).click();
  await page.getByRole('button', { name: `Agregar el cobro ${document}` }).click();
  await page.getByLabel('Aplicado (S/)').fill('400');
  await expect(page.getByText('Parcial', { exact: true })).toBeVisible();
  await expectAccessible(page);
  await page.getByRole('button', { name: 'Confirmar conciliación' }).click();

  await expect(page.getByRole('tab', { name: 'Confirmadas (1)' })).toBeVisible();
  await expect(page.getByRole('tab', { name: 'Libres (0)' })).toBeVisible();
});
