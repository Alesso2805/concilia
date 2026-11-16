import { HttpErrorResponse } from '@angular/common/http';
import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';

import { MatchDetailView } from '../../api/models/match-detail-view';
import { provideLocale } from '../../core/locale';
import { SessionStore } from '../../core/session/session.store';
import { MatchDetailDialog } from './match-detail.dialog';
import { MatchingService } from './matching.service';

const DETAIL: MatchDetailView = {
  id: 'm1',
  bank_account_id: 'a1',
  source: 'engine',
  rule: 'R3',
  score: 85,
  status: 'proposed',
  suggested_difference_reason: 'rounding',
  explanation: 'La descripción menciona F001-123 y la diferencia está dentro de la tolerancia.',
  created_at: '2027-02-03T15:00:00Z',
  credits: [
    {
      id: 'c1',
      booked_on: '2027-01-05',
      description: 'PAGO FACT F001-123',
      operation_number: null,
      amount_cents: 117_950,
    },
  ],
  receivables: [
    {
      id: 'r1',
      doc_number: 'F001-123',
      customer_name: 'Comercial Andina SAC',
      due_on: '2027-01-31',
      amount_cents: 118_000,
      applied_cents: 118_000,
      available_cents: 0,
    },
  ],
  decisions: [],
  credits_cents: 117_950,
  applied_cents: 118_000,
  difference_cents: -50,
};

describe('MatchDetailDialog', () => {
  let fixture: ComponentFixture<MatchDetailDialog>;
  let decide: ReturnType<typeof vi.fn>;
  let close: ReturnType<typeof vi.fn>;

  async function render(detail: MatchDetailView, roles: string[]): Promise<HTMLElement> {
    decide = vi.fn(() => Promise.resolve({}));
    close = vi.fn();
    TestBed.configureTestingModule({
      imports: [MatchDetailDialog],
      providers: [
        provideLocale(),
        { provide: MAT_DIALOG_DATA, useValue: detail.id },
        { provide: MatDialogRef, useValue: { close } },
        { provide: MatchingService, useValue: { detail: () => Promise.resolve(detail), decide } },
        { provide: SessionStore, useValue: { roles: signal(new Set(roles)) } },
      ],
    });
    fixture = TestBed.createComponent(MatchDetailDialog);
    await fixture.whenStable();
    await new Promise((resolve) => setTimeout(resolve));
    await fixture.whenStable();
    return fixture.nativeElement as HTMLElement;
  }

  function button(element: HTMLElement, label: string): HTMLButtonElement | undefined {
    return [...element.querySelectorAll('button')].find(
      (candidate) => candidate.textContent?.trim() === label,
    );
  }

  it('lets an analyst confirm a difference with the suggested reason', async () => {
    const element = await render(DETAIL, ['analyst']);

    expect(element.textContent).toContain('Motivo de la diferencia');
    button(element, 'Confirmar')!.click();
    await fixture.whenStable();

    expect(decide).toHaveBeenCalledWith('m1', {
      action: 'confirm',
      difference_reason: 'rounding',
      difference_note: null,
    });
    expect(close).toHaveBeenCalledWith(true);
    expect(button(element, 'Aprobar')).toBeUndefined();
  });

  it('lets a reviewer reject a confirmed match with a reason', async () => {
    const element = await render({ ...DETAIL, status: 'confirmed' }, ['reviewer']);
    const reason = element.querySelector<HTMLTextAreaElement>('textarea')!;

    reason.value = 'El abono es de otro cliente';
    reason.dispatchEvent(new Event('input'));
    button(element, 'Rechazar')!.click();
    await fixture.whenStable();

    expect(decide).toHaveBeenCalledWith('m1', {
      action: 'reject',
      reason: 'El abono es de otro cliente',
    });
    expect(button(element, 'Confirmar')).toBeUndefined();
  });

  it('explains four eyes and stays open', async () => {
    const element = await render({ ...DETAIL, status: 'confirmed' }, ['analyst', 'reviewer']);
    decide.mockRejectedValue(
      new HttpErrorResponse({ status: 409, error: { detail: 'four_eyes' } }),
    );

    button(element, 'Aprobar')!.click();
    await fixture.whenStable();
    await new Promise((resolve) => setTimeout(resolve));
    fixture.detectChanges();

    expect(element.querySelector('[role="alert"]')?.textContent).toContain(
      'Otra persona debe decidir',
    );
    expect(close).not.toHaveBeenCalled();
  });

  it('offers only reverting an approved match, to reviewers', async () => {
    const approved = await render({ ...DETAIL, status: 'approved' }, ['reviewer']);

    expect(button(approved, 'Revertir')).toBeDefined();
    expect(button(approved, 'Aprobar')).toBeUndefined();
  });
});
