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

test('an analyst runs the engine and reviews a proposal in the inbox', async ({ page }) => {
  const run = Date.now();
  const document = `E${String(run % 1000).padStart(3, '0')}-${Math.floor(run / 1000) % 10_000_000}`;
  await openApp(page);
  const session = (await callApi(page, 'GET', '/api/app/session')) as { user_id: string };
  await callApi(page, 'PUT', `/api/app/team/members/${session.user_id}/roles`, {
    roles: ['admin', 'analyst'],
  });
  const account = (await callApi(page, 'POST', '/api/app/bank-accounts', {
    id: uuidV7(),
    bank: 'BCP',
    alias: `Bandeja ${run}`,
    number_last4: '4321',
  })) as { id: string };
  const statement = (await callApi(page, 'POST', '/api/app/import-profiles', {
    id: uuidV7(),
    kind: 'bank_statement',
    bank_account_id: account.id,
    name: `Extracto bandeja ${run}`,
    config: { ...CSV, columns: { date: 'Fecha', description: 'Detalle', amount: 'Importe' } },
  })) as { id: string };
  const receivables = (await callApi(page, 'POST', '/api/app/import-profiles', {
    id: uuidV7(),
    kind: 'receivables',
    name: `Cobros bandeja ${run}`,
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
    `bandeja-${run}.csv`,
    [
      'Fecha;Detalle;Importe',
      `05/01/2027;PAGO FACT ${document};1.180,00`,
      '09/01/2027;DEPOSITO SIN REFERENCIA;77,00',
    ].join('\n'),
  );
  await importFile(
    page,
    receivables.id,
    `cobros-bandeja-${run}.csv`,
    [
      'Cliente;Documento;Emision;Vencimiento;Monto',
      `Comercial Andina SAC;${document};02/01/2027;31/01/2027;1.180,00`,
    ].join('\n'),
  );

  await page
    .getByRole('navigation', { name: 'Principal' })
    .getByRole('link', { name: 'Bandeja' })
    .click();
  await expect(
    page.getByRole('heading', { name: 'Bandeja de conciliación', level: 1 }),
  ).toBeVisible();
  await page.getByText('Cuenta', { exact: true }).click();
  await page.getByRole('option', { name: new RegExp(`Bandeja ${run}`) }).click();
  await expect(page.getByRole('tab', { name: 'Libres (2)' })).toBeVisible();
  await expectAccessible(page);

  await page.getByRole('button', { name: 'Correr el motor' }).click();
  await expect(page.getByText('El motor propuso 1 coincidencia.')).toBeVisible();
  await expect(page.getByRole('tab', { name: 'Propuestas (1)' })).toBeVisible();
  await expect(page.getByRole('table')).toContainText(`PAGO FACT ${document}`);
  await expect(page.getByRole('table')).toContainText('S/ 1,180.00');
  await expectAccessible(page);

  await page.getByRole('button', { name: `Ver detalle de PAGO FACT ${document}` }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toContainText(`La descripción menciona ${document}`);
  await expect(dialog).toContainText('Comercial Andina SAC');
  await expectAccessible(page);
  await dialog.getByRole('button', { name: 'Cerrar' }).click();

  await page.getByRole('tab', { name: 'Libres (1)' }).click();
  await expect(page.getByRole('table')).toContainText('DEPOSITO SIN REFERENCIA');
});
