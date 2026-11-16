import { HttpErrorResponse } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MatDialog } from '@angular/material/dialog';
import { Router, provideRouter } from '@angular/router';
import { of } from 'rxjs';

import { ImportSummaryView } from '../../api/models/import-summary-view';
import { JobTracker } from '../../core/jobs/job-tracker';
import { provideLocale } from '../../core/locale';
import { BankingService } from '../admin/banking.service';
import { ImportPage } from './import.page';
import { ImportsPage } from './imports.page';
import { ImportsService } from './imports.service';

const FILE = {
  id: 'f1',
  kind: 'bank_statement' as const,
  bank_account_id: 'a1',
  import_profile_id: 'p1',
  profile_name: 'BCP soles',
  filename: 'enero.csv',
  size_bytes: 120,
  status: 'previewed' as const,
  error_code: null,
  row_count: 4,
  created_at: '2027-02-03T15:00:00Z',
  confirmed_at: null,
  discarded_at: null,
  voided_at: null,
};
const COUNTS = { ok: 3, error: 1, duplicate: 0, closed_period: 0, conflict: 0 };
const STATEMENT_ROW = {
  kind: 'statement',
  row_number: 2,
  status: 'ok',
  booked_on: '2027-01-05',
  amount_cents: 118_000,
  description: 'PAGO FACT F001-123',
  operation_number: null,
};
const RECEIVABLE_ROW = {
  kind: 'receivable',
  row_number: 2,
  status: 'ok',
  action: 'update',
  conflict: null,
  customer_name: 'Comercial Andina SAC',
  customer_tax_id: '20512345678',
  doc_number: 'F001-123',
  issued_on: '2027-01-02',
  due_on: '2027-02-28',
  amount_cents: 120_000,
  previous_due_on: '2027-01-31',
  previous_amount_cents: 118_000,
};
const RECEIVABLES_FILE = {
  ...FILE,
  kind: 'receivables' as const,
  bank_account_id: null,
  profile_name: 'Facturas',
};

async function settle(fixture: ComponentFixture<unknown>): Promise<void> {
  await fixture.whenStable();
  await new Promise((resolve) => setTimeout(resolve));
  await fixture.whenStable();
}

function text(fixture: ComponentFixture<unknown>): string {
  return ((fixture.nativeElement as HTMLElement).textContent ?? '').replace(/\s+/g, ' ');
}

describe('ImportsPage', () => {
  let fixture: ComponentFixture<ImportsPage>;
  let upload: ReturnType<typeof vi.fn>;
  let navigate: ReturnType<typeof vi.spyOn>;

  async function render(profiles: unknown[]): Promise<HTMLElement> {
    upload = vi.fn(() => Promise.resolve({ file: FILE, job_id: 'j1', duplicate_of: null }));
    TestBed.configureTestingModule({
      imports: [ImportsPage],
      providers: [
        provideRouter([]),
        provideLocale(),
        {
          provide: ImportsService,
          useValue: {
            upload,
            list: () =>
              Promise.resolve({
                files: [FILE],
                has_next: false,
                has_previous: false,
                next_cursor: null,
                previous_cursor: null,
              }),
          },
        },
        { provide: BankingService, useValue: { profiles: () => Promise.resolve(profiles) } },
      ],
    });
    navigate = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    fixture = TestBed.createComponent(ImportsPage);
    await settle(fixture);
    return fixture.nativeElement as HTMLElement;
  }

  it('asks for a profile when there is none', async () => {
    await render([]);

    expect(text(fixture)).toContain('Todavía no hay perfiles de importación.');
    expect(text(fixture)).toContain('Extracto');
    expect(text(fixture)).toContain('enero.csv');
  });

  it('uploads the chosen file and follows its job', async () => {
    const element = await render([
      { id: 'p1', kind: 'bank_statement', name: 'BCP soles', archived_at: null },
      { id: 'p2', kind: 'receivables', name: 'Facturas', archived_at: null },
    ]);
    const page = fixture.componentInstance as unknown as {
      profile: { setValue(value: string): void };
      choose(event: Event): void;
    };
    const file = new File(['Fecha;Detalle;Importe'], 'enero.csv', { type: 'text/csv' });
    page.profile.setValue('p1');
    page.choose({ target: { files: { item: () => file } } } as unknown as Event);

    [...element.querySelectorAll('button')]
      .find((button) => button.textContent?.includes('Subir y revisar'))!
      .click();
    await settle(fixture);

    expect(upload).toHaveBeenCalledWith('p1', file);
    expect(navigate).toHaveBeenCalledWith(['/importaciones', 'f1'], {
      queryParams: { trabajo: 'j1' },
    });
  });
});

describe('ImportPage', () => {
  let fixture: ComponentFixture<ImportPage>;
  let service: Record<string, ReturnType<typeof vi.fn>>;
  let track: ReturnType<typeof vi.fn>;

  async function render(
    summary: ImportSummaryView,
    job?: string,
    rows: unknown[] = [STATEMENT_ROW],
  ): Promise<HTMLElement> {
    service = {
      summary: vi.fn(() => Promise.resolve(summary)),
      rows: vi.fn(() => Promise.resolve({ rows, has_previous: false, has_next: false })),
      confirm: vi.fn(() => Promise.resolve('j2')),
    };
    track = vi.fn(() => of({ id: 'j2', kind: 'confirm_import', status: 'done', progress: 100 }));
    TestBed.configureTestingModule({
      imports: [ImportPage],
      providers: [
        provideRouter([]),
        provideLocale(),
        { provide: ImportsService, useValue: service },
        { provide: JobTracker, useValue: { track } },
        { provide: MatDialog, useValue: { open: vi.fn() } },
      ],
    });
    fixture = TestBed.createComponent(ImportPage);
    fixture.componentRef.setInput('id', 'f1');
    if (job) {
      fixture.componentRef.setInput('trabajo', job);
    }
    await settle(fixture);
    return fixture.nativeElement as HTMLElement;
  }

  it('shows the preview with counts and valid rows', async () => {
    await render({ file: FILE, counts: COUNTS, duplicate_of: 'f0' });

    expect(text(fixture)).toContain('Ya confirmaste un archivo idéntico');
    expect(text(fixture)).toContain('Válidas (3)');
    expect(text(fixture)).toContain('Con errores (1)');
    expect(text(fixture)).toContain('S/ 1,180.00');
    expect(service['rows']).toHaveBeenCalledWith('f1', 'ok', {});
  });

  it('confirms and follows the confirmation job', async () => {
    const element = await render({ file: FILE, counts: COUNTS, duplicate_of: null });

    [...element.querySelectorAll('button')]
      .find((button) => button.textContent?.includes('Confirmar 3 movimientos'))!
      .click();
    await settle(fixture);

    expect(service['confirm']).toHaveBeenCalledWith('f1');
    expect(track).toHaveBeenCalledWith('j2');
    expect(service['summary']).toHaveBeenCalledTimes(2);
  });

  it('follows the parse job of a new upload', async () => {
    await render(
      {
        file: { ...FILE, status: 'uploaded', row_count: null },
        counts: COUNTS,
        duplicate_of: null,
      },
      'j1',
    );

    expect(track).toHaveBeenCalledWith('j1');
  });

  it('explains why a file failed', async () => {
    await render({
      file: { ...FILE, status: 'failed', error_code: 'missing_columns' },
      counts: COUNTS,
      duplicate_of: null,
    });

    expect(text(fixture)).toContain('Faltan columnas del perfil en el encabezado.');
  });

  it('offers to void a confirmed import', async () => {
    await render({
      file: { ...FILE, status: 'confirmed', confirmed_at: '2027-02-03T16:00:00Z' },
      counts: COUNTS,
      duplicate_of: null,
    });

    expect(text(fixture)).toContain('Anular importación');
  });

  it('shows a receivables preview with what each row changes', async () => {
    await render(
      { file: RECEIVABLES_FILE, counts: { ...COUNTS, ok: 2, conflict: 1 }, duplicate_of: 'f0' },
      undefined,
      [RECEIVABLE_ROW],
    );

    expect(text(fixture)).toContain('Ya confirmaste un archivo idéntico en esta organización.');
    expect(text(fixture)).toContain('Nuevos o con cambios (2)');
    expect(text(fixture)).toContain('En conflicto (1)');
    expect(text(fixture)).toContain('Comercial Andina SAC');
    expect(text(fixture)).toContain('Antes: vence 31/01/2027, S/ 1,180.00');
    expect(text(fixture)).toContain('Confirmar 2 cobros');
  });

  it('says what a voided receivables import did', async () => {
    await render({
      file: { ...RECEIVABLES_FILE, status: 'voided', voided_at: '2027-02-03T16:00:00Z' },
      counts: COUNTS,
      duplicate_of: null,
    });

    expect(text(fixture)).toContain('Los cobros que creó quedaron anulados.');
  });

  it('reports a failed confirmation', async () => {
    const element = await render({ file: FILE, counts: COUNTS, duplicate_of: null });
    service['confirm'].mockImplementation(() =>
      Promise.reject(new HttpErrorResponse({ status: 409, error: { detail: 'duplicate_file' } })),
    );

    [...element.querySelectorAll('button')]
      .find((button) => button.textContent?.includes('Confirmar'))!
      .click();
    await settle(fixture);

    expect(element.querySelector('[role="alert"]')?.textContent).toContain(
      'Ya confirmaste un archivo idéntico.',
    );
  });
});
