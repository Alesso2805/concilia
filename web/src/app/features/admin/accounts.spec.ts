import { HttpErrorResponse } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MAT_DIALOG_DATA, MatDialog, MatDialogRef } from '@angular/material/dialog';
import { of } from 'rxjs';

import { BankAccountView } from '../../api/models/bank-account-view';
import { provideIcons } from '../../core/icons';
import { AccountDialog } from './account.dialog';
import { AccountsPage } from './accounts.page';
import { BankingService } from './banking.service';
import { ConfirmDialog } from './confirm.dialog';

const ACTIVE: BankAccountView = {
  id: 'a1',
  bank: 'BCP',
  currency: 'PEN',
  alias: 'Recaudación',
  number_last4: '4521',
  created_at: '2026-11-20T10:00:00Z',
  archived_at: null,
};
const ARCHIVED: BankAccountView = {
  ...ACTIVE,
  id: 'a2',
  alias: 'Antigua',
  archived_at: '2026-11-21T10:00:00Z',
};

function rows(element: HTMLElement): string[] {
  return [...element.querySelectorAll('tr.mat-mdc-row')].map((row) =>
    [...row.querySelectorAll('td')]
      .map((cell) => cell.textContent?.replace(/\s+/g, ' ').trim())
      .filter(Boolean)
      .join(' | '),
  );
}

describe('AccountsPage', () => {
  let fixture: ComponentFixture<AccountsPage>;
  let open: ReturnType<typeof vi.fn>;

  beforeEach(async () => {
    open = vi.fn(() => ({ afterClosed: () => of(false) }));
    TestBed.configureTestingModule({
      imports: [AccountsPage],
      providers: [
        provideIcons(),
        {
          provide: BankingService,
          useValue: { accounts: () => Promise.resolve([ACTIVE, ARCHIVED]) },
        },
        { provide: MatDialog, useValue: { open } },
      ],
    });
    fixture = TestBed.createComponent(AccountsPage);
    await fixture.whenStable();
  });

  it('lists active accounts and hides archived ones until asked', async () => {
    const element = fixture.nativeElement as HTMLElement;
    expect(rows(element)).toEqual(['BCP | Recaudación | •••• terminada en 4521 | Activa']);

    element.querySelector<HTMLButtonElement>('mat-slide-toggle button')!.click();
    await fixture.whenStable();

    expect(rows(element)[1]).toBe('BCP | Antigua | •••• terminada en 4521 | Archivada');
  });

  it('asks before archiving', async () => {
    const element = fixture.nativeElement as HTMLElement;

    element.querySelector<HTMLButtonElement>('[aria-label="Archivar Recaudación"]')!.click();
    await fixture.whenStable();

    const [component, config] = open.mock.calls[0];
    expect(component).toBe(ConfirmDialog);
    expect(config.data.title).toBe('¿Archivar «Recaudación»?');
  });
});

describe('AccountDialog', () => {
  async function render(
    account: BankAccountView | null,
    banking: Record<string, unknown>,
  ): Promise<{ fixture: ComponentFixture<AccountDialog>; close: ReturnType<typeof vi.fn> }> {
    const close = vi.fn();
    TestBed.configureTestingModule({
      imports: [AccountDialog],
      providers: [
        { provide: BankingService, useValue: banking },
        { provide: MatDialogRef, useValue: { close } },
        { provide: MAT_DIALOG_DATA, useValue: account },
      ],
    });
    const fixture = TestBed.createComponent(AccountDialog);
    await fixture.whenStable();
    return { fixture, close };
  }

  function type(fixture: ComponentFixture<AccountDialog>, name: string, value: string): void {
    const input = (fixture.nativeElement as HTMLElement).querySelector<HTMLInputElement>(
      `input[formcontrolname="${name}"]`,
    )!;
    input.value = value;
    input.dispatchEvent(new Event('input'));
  }

  async function submit(fixture: ComponentFixture<AccountDialog>): Promise<void> {
    (fixture.nativeElement as HTMLElement)
      .querySelector('form')!
      .dispatchEvent(new Event('submit'));
    await fixture.whenStable();
  }

  it('edits an account with its current values', async () => {
    const updateAccount = vi.fn(() => Promise.resolve());
    const { fixture, close } = await render(ACTIVE, { updateAccount });

    type(fixture, 'alias', 'Recaudación soles');
    await submit(fixture);

    expect(updateAccount).toHaveBeenCalledWith('a1', {
      bank: 'BCP',
      alias: 'Recaudación soles',
      number_last4: '4521',
    });
    expect(close).toHaveBeenCalledWith(true);
  });

  it('needs exactly four digits', async () => {
    const createAccount = vi.fn();
    const { fixture } = await render(null, { createAccount });

    type(fixture, 'alias', 'Nueva');
    type(fixture, 'number_last4', '12a4');
    await submit(fixture);

    expect(createAccount).not.toHaveBeenCalled();
  });

  it('explains a server rejection', async () => {
    const updateAccount = () =>
      Promise.reject(new HttpErrorResponse({ status: 409, error: { detail: 'archived' } }));
    const { fixture, close } = await render(ACTIVE, { updateAccount });

    await submit(fixture);

    expect((fixture.nativeElement as HTMLElement).textContent).toContain('Está archivado');
    expect(close).not.toHaveBeenCalled();
  });
});
