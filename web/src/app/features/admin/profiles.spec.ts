import { ComponentFixture, TestBed } from '@angular/core/testing';
import { NonNullableFormBuilder } from '@angular/forms';
import { MatDialog } from '@angular/material/dialog';
import { Router, provideRouter } from '@angular/router';

import { BankAccountView } from '../../api/models/bank-account-view';
import { StatementConfig } from '../../api/models/statement-config';
import { provideIcons } from '../../core/icons';
import { BankingService, ProfileView, TemplateView } from './banking.service';
import { ProfileEditorPage } from './profile-editor.page';
import { applyConfig, profileForm, toDraft } from './profile-form';
import { ProfilesPage } from './profiles.page';

const ACCOUNT: BankAccountView = {
  id: 'a1',
  bank: 'Interbank',
  currency: 'PEN',
  alias: 'Recaudación',
  number_last4: '4521',
  created_at: '2026-11-20T10:00:00Z',
  archived_at: null,
};
const SPLIT: StatementConfig = {
  format: 'xlsx',
  skip_rows: 6,
  date_format: 'DD/MM/YYYY',
  columns: {
    date: 'Fecha de operación',
    description: 'Descripción',
    operation_number: 'Nro. de operación',
    debit: 'Cargo',
    credit: 'Abono',
  },
};
const TEMPLATE: TemplateView = {
  key: 'interbank',
  name: 'Interbank · movimientos en Excel',
  bank: 'Interbank',
  kind: 'bank_statement',
  config: SPLIT,
};
const PROFILE: ProfileView = {
  id: 'p1',
  kind: 'bank_statement',
  bank_account_id: 'a1',
  name: 'Interbank soles',
  config: SPLIT,
  created_at: '2026-11-20T10:00:00Z',
  archived_at: null,
};

describe('profile form', () => {
  function form() {
    return TestBed.runInInjectionContext(() => profileForm(TestBed.inject(NonNullableFormBuilder)));
  }

  it('turns a split-amount template into a statement draft', () => {
    const profile = form();
    applyConfig(profile, 'bank_statement', SPLIT);
    profile.patchValue({ name: 'Interbank', bank_account_id: 'a1' });

    expect(profile.valid).toBe(true);
    expect(profile.controls.statement.controls.amount.disabled).toBe(true);
    expect(toDraft(profile)).toEqual({
      kind: 'bank_statement',
      name: 'Interbank',
      bank_account_id: 'a1',
      config: {
        format: 'xlsx',
        sheet: null,
        encoding: 'utf-8',
        delimiter: ',',
        skip_rows: 6,
        date_format: 'DD/MM/YYYY',
        decimal_separator: '.',
        thousands_separator: '',
        columns: { ...SPLIT.columns, amount: null },
      },
    });
  });

  it('builds a receivables draft without an account', () => {
    const profile = form();
    applyConfig(profile, 'receivables', {
      format: 'csv',
      delimiter: ';',
      date_format: 'YYYY-MM-DD',
      columns: {
        customer_name: 'Cliente',
        doc_number: 'Factura',
        issued_on: 'Emisión',
        due_on: 'Vence',
        amount: 'Total',
      },
    });
    profile.controls.name.setValue('Facturas');

    const draft = toDraft(profile);
    expect(profile.valid).toBe(true);
    expect(profile.controls.bank_account_id.disabled).toBe(true);
    expect(draft).toMatchObject({ kind: 'receivables', config: { delimiter: ';', sheet: null } });
    expect('bank_account_id' in draft).toBe(false);
  });

  it('rejects equal separators and repeated columns', () => {
    const profile = form();
    applyConfig(profile, 'bank_statement', {
      ...SPLIT,
      decimal_separator: ',',
      thousands_separator: ',',
      columns: { ...SPLIT.columns, credit: 'cargo' },
    });

    expect(profile.hasError('separators')).toBe(true);
    expect(profile.controls.statement.hasError('duplicated')).toBe(true);
  });
});

describe('ProfileEditorPage', () => {
  let fixture: ComponentFixture<ProfileEditorPage>;
  let banking: Record<string, ReturnType<typeof vi.fn>>;
  let navigateByUrl: ReturnType<typeof vi.spyOn>;

  async function render(id?: string): Promise<HTMLElement> {
    banking = {
      accounts: vi.fn(() => Promise.resolve([ACCOUNT])),
      templates: vi.fn(() => Promise.resolve([TEMPLATE])),
      profiles: vi.fn(() => Promise.resolve([PROFILE])),
      createProfile: vi.fn(() => Promise.resolve(PROFILE)),
      updateProfile: vi.fn(() => Promise.resolve()),
    };
    TestBed.configureTestingModule({
      imports: [ProfileEditorPage],
      providers: [provideRouter([]), { provide: BankingService, useValue: banking }],
    });
    navigateByUrl = vi.spyOn(TestBed.inject(Router), 'navigateByUrl').mockResolvedValue(true);
    fixture = TestBed.createComponent(ProfileEditorPage);
    if (id) {
      fixture.componentRef.setInput('id', id);
    }
    await settle();
    return fixture.nativeElement as HTMLElement;
  }

  async function settle(): Promise<void> {
    await fixture.whenStable();
    await new Promise((resolve) => setTimeout(resolve));
    await fixture.whenStable();
  }

  it('creates a profile from a template for the chosen account', async () => {
    const element = await render();
    const page = fixture.componentInstance as unknown as {
      useTemplate(key: string): void;
      form: ReturnType<typeof profileForm>;
    };

    page.useTemplate('interbank');
    page.form.controls.bank_account_id.setValue('a1');
    await settle();
    expect(element.textContent).toContain('verifica los nombres de columna');
    element.querySelector('form')!.dispatchEvent(new Event('submit'));
    await settle();

    expect(banking['createProfile']).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: 'bank_statement',
        name: 'Interbank · movimientos en Excel',
        bank_account_id: 'a1',
      }),
    );
    expect(navigateByUrl).toHaveBeenCalledWith('/perfiles');
  });

  it('does not save without an account', async () => {
    const element = await render();

    (fixture.componentInstance as unknown as { useTemplate(key: string): void }).useTemplate(
      'interbank',
    );
    element.querySelector('form')!.dispatchEvent(new Event('submit'));
    await settle();

    expect(banking['createProfile']).not.toHaveBeenCalled();
  });

  it('edits an existing profile keeping its kind and account', async () => {
    const element = await render('p1');

    const name = element.querySelector<HTMLInputElement>('input[formcontrolname="name"]')!;
    expect(name.value).toBe('Interbank soles');
    name.value = 'Interbank recaudación';
    name.dispatchEvent(new Event('input'));
    element.querySelector('form')!.dispatchEvent(new Event('submit'));
    await settle();

    expect(banking['updateProfile']).toHaveBeenCalledWith(
      'p1',
      expect.objectContaining({ name: 'Interbank recaudación', bank_account_id: 'a1' }),
    );
  });
});

describe('ProfilesPage', () => {
  it('lists profiles with their account', async () => {
    TestBed.configureTestingModule({
      imports: [ProfilesPage],
      providers: [
        provideRouter([]),
        provideIcons(),
        {
          provide: BankingService,
          useValue: {
            profiles: () => Promise.resolve([PROFILE]),
            accounts: () => Promise.resolve([ACCOUNT]),
          },
        },
        { provide: MatDialog, useValue: { open: vi.fn() } },
      ],
    });
    const fixture = TestBed.createComponent(ProfilesPage);
    await fixture.whenStable();
    await new Promise((resolve) => setTimeout(resolve));
    await fixture.whenStable();

    const cells = [...(fixture.nativeElement as HTMLElement).querySelectorAll('tr.mat-mdc-row td')]
      .map((cell) => cell.textContent?.trim())
      .filter(Boolean);
    expect(cells).toEqual([
      'Interbank soles',
      'Extracto bancario',
      'Recaudación ···· 4521',
      'Activo',
    ]);
  });
});
