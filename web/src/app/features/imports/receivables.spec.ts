import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MatDialog } from '@angular/material/dialog';
import { of } from 'rxjs';

import { ReceivableView } from '../../api/models/receivable-view';
import { provideLocale } from '../../core/locale';
import { SessionStore } from '../../core/session/session.store';
import { ImportsService } from './imports.service';
import { ReasonData } from './reason.dialog';
import { ReceivablesPage } from './receivables.page';

const RECEIVABLE: ReceivableView = {
  id: 'r1',
  import_file_id: 'f1',
  customer_name: 'Comercial Andina SAC',
  customer_tax_id: '20512345678',
  doc_number: 'F001-123',
  issued_on: '2027-01-02',
  due_on: '2027-01-31',
  amount_cents: 118_000,
  cancelled_at: null,
  cancel_reason: null,
};

async function settle(fixture: ComponentFixture<unknown>): Promise<void> {
  await fixture.whenStable();
  await new Promise((resolve) => setTimeout(resolve));
  await fixture.whenStable();
}

function text(fixture: ComponentFixture<unknown>): string {
  return ((fixture.nativeElement as HTMLElement).textContent ?? '').replace(/\s+/g, ' ');
}

describe('ReceivablesPage', () => {
  let fixture: ComponentFixture<ReceivablesPage>;
  let receivables: ReturnType<typeof vi.fn>;
  let cancelReceivable: ReturnType<typeof vi.fn>;
  let open: ReturnType<typeof vi.fn>;

  async function render(roles: string[]): Promise<HTMLElement> {
    receivables = vi.fn(() =>
      Promise.resolve({
        receivables: [RECEIVABLE],
        has_previous: false,
        has_next: false,
        previous_cursor: 'c0',
        next_cursor: 'c1',
      }),
    );
    cancelReceivable = vi.fn(() => Promise.resolve());
    open = vi.fn(() => ({ afterClosed: () => of(true) }));
    TestBed.configureTestingModule({
      imports: [ReceivablesPage],
      providers: [
        provideLocale(),
        { provide: ImportsService, useValue: { receivables, cancelReceivable } },
        { provide: SessionStore, useValue: { roles: signal(new Set(roles)) } },
        { provide: MatDialog, useValue: { open } },
      ],
    });
    fixture = TestBed.createComponent(ReceivablesPage);
    await settle(fixture);
    return fixture.nativeElement as HTMLElement;
  }

  function button(element: HTMLElement, label: string): HTMLButtonElement {
    return [...element.querySelectorAll('button')].find(
      (candidate) => candidate.textContent?.trim() === label,
    )!;
  }

  it('lists the live receivables with a cancel action for analysts', async () => {
    const element = await render(['analyst']);

    expect(receivables).toHaveBeenCalledWith({ cancelled: false, document: null });
    expect(text(fixture)).toContain('Comercial Andina SAC');
    expect(text(fixture)).toContain('S/ 1,180.00');
    expect(button(element, 'Anular')).toBeTruthy();
  });

  it('shows no cancel action to other roles', async () => {
    const element = await render(['reviewer']);

    expect(text(fixture)).toContain('F001-123');
    expect(button(element, 'Anular')).toBeUndefined();
  });

  it('searches by document number and can go back to the full list', async () => {
    const element = await render(['analyst']);
    const page = fixture.componentInstance as unknown as {
      search: { controls: { document: { setValue(value: string): void } } };
    };

    page.search.controls.document.setValue(' F1-123 ');
    button(element, 'Buscar').click();
    await settle(fixture);
    expect(receivables).toHaveBeenLastCalledWith({ cancelled: false, document: 'F1-123' });

    button(element, 'Ver todos').click();
    await settle(fixture);
    expect(receivables).toHaveBeenLastCalledWith({ cancelled: false, document: null });
  });

  it('cancels with a reason and reloads', async () => {
    const element = await render(['analyst']);

    button(element, 'Anular').click();
    await settle(fixture);
    const data = open.mock.calls[0][1].data as ReasonData;
    await data.run('Nota de crédito');

    expect(data.title).toBe('¿Anular el cobro F001-123?');
    expect(cancelReceivable).toHaveBeenCalledWith('r1', 'Nota de crédito');
    expect(receivables).toHaveBeenCalledTimes(2);
  });
});
