import { HttpErrorResponse } from '@angular/common/http';
import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MatDialog } from '@angular/material/dialog';
import { provideRouter } from '@angular/router';
import { of } from 'rxjs';

import { MatchRowView } from '../../api/models/match-row-view';
import { JobTracker } from '../../core/jobs/job-tracker';
import { provideLocale } from '../../core/locale';
import { SessionStore } from '../../core/session/session.store';
import { BankingService } from '../admin/banking.service';
import { AiService } from '../ai/ai.service';
import { SuggestionDialog } from '../ai/suggestion.dialog';
import { PeriodsService } from '../periods/periods.service';
import { ReopenPeriodDialog } from '../periods/reopen-period.dialog';
import { InboxPage } from './inbox.page';
import { monthLabel } from './labels';
import { MatchDetailDialog } from './match-detail.dialog';
import { MatchingService } from './matching.service';

const MATCH: MatchRowView = {
  id: 'm1',
  source: 'engine',
  rule: 'R1',
  score: 100,
  status: 'proposed',
  booked_on: '2027-01-05',
  description: 'PAGO FACT F001-123',
  documents: ['F001-123'],
  customers: ['Comercial Andina SAC'],
  credits_cents: 118_000,
  applied_cents: 118_000,
  difference_cents: 0,
};
const CREDIT = {
  id: 'c1',
  booked_on: '2027-02-07',
  description: 'TRANSF CLIENTE',
  operation_number: null,
  amount_cents: 50_000,
};
const PAGE = { has_previous: false, has_next: false, previous_cursor: null, next_cursor: null };

async function settle(fixture: ComponentFixture<unknown>): Promise<void> {
  for (let round = 0; round < 3; round++) {
    await fixture.whenStable();
    await new Promise((resolve) => setTimeout(resolve));
  }
}

function text(fixture: ComponentFixture<unknown>): string {
  return ((fixture.nativeElement as HTMLElement).textContent ?? '').replace(/\s+/g, ' ');
}

function button(element: HTMLElement, label: string): HTMLButtonElement {
  return [...element.querySelectorAll('button')].find(
    (candidate) => candidate.textContent?.trim() === label,
  )!;
}

describe('InboxPage', () => {
  let fixture: ComponentFixture<InboxPage>;
  let service: Record<string, ReturnType<typeof vi.fn>>;
  let open: ReturnType<typeof vi.fn>;
  let periodsApi: Record<string, ReturnType<typeof vi.fn>>;

  async function render(
    roles: string[],
    closed = false,
    usage: object | null = null,
  ): Promise<HTMLElement> {
    service = {
      periods: vi.fn(() =>
        Promise.resolve([
          { period: '2027-02-01', closed, credits: 3 },
          { period: '2027-01-01', closed: false, credits: 5 },
        ]),
      ),
      counts: vi.fn(() => Promise.resolve({ free: 2, proposed: 1, confirmed: 0, approved: 0 })),
      matches: vi.fn(() => Promise.resolve({ matches: [MATCH], ...PAGE })),
      credits: vi.fn(() => Promise.resolve({ credits: [CREDIT], ...PAGE })),
      runEngine: vi.fn(() => Promise.resolve({ id: 'run1', job_id: 'j1' })),
      run: vi.fn(() => Promise.resolve({ id: 'run1', proposals_count: 1 })),
      decideBatch: vi.fn(() => Promise.resolve({ decided: 2, skipped: 1 })),
    };
    open = vi.fn(() => ({ afterClosed: () => of(false) }));
    periodsApi = {
      close: vi.fn(() => Promise.resolve({})),
      reopen: vi.fn(() => Promise.resolve({})),
    };
    TestBed.configureTestingModule({
      imports: [InboxPage],
      providers: [
        provideRouter([]),
        provideLocale(),
        { provide: MatchingService, useValue: service },
        {
          provide: BankingService,
          useValue: {
            accounts: () =>
              Promise.resolve([
                {
                  id: 'a1',
                  bank: 'BCP',
                  alias: 'Principal',
                  number_last4: '1234',
                  archived_at: null,
                },
              ]),
          },
        },
        {
          provide: JobTracker,
          useValue: { track: () => of({ id: 'j1', status: 'done', progress: 100 }) },
        },
        { provide: SessionStore, useValue: { roles: signal(new Set(roles)) } },
        { provide: MatDialog, useValue: { open } },
        { provide: PeriodsService, useValue: periodsApi },
        { provide: AiService, useValue: { usage: () => Promise.resolve(usage) } },
      ],
    });
    fixture = TestBed.createComponent(InboxPage);
    await settle(fixture);
    return fixture.nativeElement as HTMLElement;
  }

  it('opens the newest month of the first account on the proposals', async () => {
    await render(['analyst']);
    const month = { accountId: 'a1', period: '2027-02-01' };

    expect(service['counts']).toHaveBeenCalledWith(month);
    expect(service['matches']).toHaveBeenCalledWith(
      month,
      'proposed',
      { rule: null, minScore: null, minAmountCents: null, maxAmountCents: null },
      {},
    );
    const tabs = [...(fixture.nativeElement as HTMLElement).querySelectorAll('[role="tab"]')];
    expect(tabs.map((tab) => tab.textContent?.replace(/\s+/g, ' ').trim())).toEqual([
      'Libres 2',
      'Propuestas 1',
      'Confirmadas 0',
      'Aprobadas 0',
    ]);
    expect(text(fixture)).toContain('PAGO FACT F001-123');
    expect(text(fixture)).toContain('S/ 1,180.00');
    expect(text(fixture)).toContain('R1 · Exacta');
  });

  it('names the account and the month and says whether the month is open', async () => {
    await render(['analyst']);

    expect(text(fixture)).toContain('febrero de 2027 Mes abierto');
  });

  it('runs the engine, follows its job and reports the proposals', async () => {
    const element = await render(['analyst']);

    button(element, 'Correr el motor').click();
    await settle(fixture);

    expect(service['runEngine']).toHaveBeenCalledWith({ accountId: 'a1', period: '2027-02-01' });
    expect(service['run']).toHaveBeenCalledWith('run1');
    expect(text(fixture)).toContain('El motor propuso 1 coincidencia.');
    expect(service['counts']).toHaveBeenCalledTimes(2);
  });

  it('lets only analysts run the engine, and never on a closed month', async () => {
    const reviewer = await render(['reviewer']);
    expect(button(reviewer, 'Correr el motor').disabled).toBe(true);
    TestBed.resetTestingModule();

    const closed = await render(['analyst'], true);
    expect(button(closed, 'Correr el motor').disabled).toBe(true);
    expect(text(fixture)).toContain('Este mes está cerrado');
  });

  it('filters by rule, score and amount, and explains invalid filters', async () => {
    const element = await render(['analyst']);
    const page = fixture.componentInstance as unknown as {
      filterForm: { patchValue(value: object): void };
    };

    page.filterForm.patchValue({ minScore: '200' });
    button(element, 'Filtrar').click();
    await settle(fixture);
    expect(text(fixture)).toContain('Revisa los filtros');

    page.filterForm.patchValue({ rule: 'R1', minScore: '90', minAmount: '100,50', maxAmount: '' });
    button(element, 'Filtrar').click();
    await settle(fixture);
    expect(service['matches']).toHaveBeenLastCalledWith(
      { accountId: 'a1', period: '2027-02-01' },
      'proposed',
      { rule: 'R1', minScore: 90, minAmountCents: 10_050, maxAmountCents: null },
      {},
    );
  });

  it('opens the detail of a match', async () => {
    const element = await render(['reviewer']);

    button(element, 'Ver detalle').click();

    expect(open).toHaveBeenCalledWith(MatchDetailDialog, {
      data: 'm1',
      autoFocus: 'dialog',
      panelClass: 'app-wide-dialog',
    });
  });

  it('confirms the score 100 proposals in batch for analysts only', async () => {
    const element = await render(['analyst']);

    button(element, 'Confirmar todas las de puntaje 100').click();
    await settle(fixture);

    expect(service['decideBatch']).toHaveBeenCalledWith(
      { accountId: 'a1', period: '2027-02-01' },
      'confirm',
    );
    expect(text(fixture)).toContain(
      'Se confirmaron 2 coincidencias. Una queda para otra persona porque tú las creaste o confirmaste.',
    );
    TestBed.resetTestingModule();

    const reviewer = await render(['reviewer']);
    expect(button(reviewer, 'Confirmar todas las de puntaje 100')).toBeUndefined();
  });

  it('lets reviewers close an open month', async () => {
    const element = await render(['reviewer']);

    button(element, 'Cerrar mes').click();
    await settle(fixture);

    expect(periodsApi['close']).toHaveBeenCalledWith({ accountId: 'a1', period: '2027-02-01' });
    expect(service['periods']).toHaveBeenCalledTimes(2);
    expect(text(fixture)).toContain('Cerraste febrero de 2027.');
    TestBed.resetTestingModule();

    const analyst = await render(['analyst']);
    expect(button(analyst, 'Cerrar mes')).toBeUndefined();
  });

  it('reopens a closed month with the reason given in its dialog', async () => {
    const element = await render(['reviewer'], true);
    expect(button(element, 'Cerrar mes')).toBeUndefined();
    open.mockReturnValue({ afterClosed: () => of('Faltó un abono') });

    button(element, 'Reabrir mes').click();
    await settle(fixture);

    expect(open).toHaveBeenCalledWith(ReopenPeriodDialog, {
      data: 'febrero de 2027',
      autoFocus: 'first-tabbable',
    });
    expect(periodsApi['reopen']).toHaveBeenCalledWith(
      { accountId: 'a1', period: '2027-02-01' },
      'Faltó un abono',
    );
    expect(text(fixture)).toContain('Reabriste febrero de 2027.');
  });

  it('explains why a month with pending matches stays open', async () => {
    const element = await render(['reviewer']);
    periodsApi['close'].mockRejectedValue(
      new HttpErrorResponse({ status: 409, error: { detail: 'pending_matches' } }),
    );

    button(element, 'Cerrar mes').click();
    await settle(fixture);

    expect(text(fixture)).toContain('Quedan coincidencias propuestas o confirmadas en este mes');
  });

  it('offers analysts the AI on free credits when it is available', async () => {
    interface AiInbox {
      creditColumns(): string[];
      askAi(credit: typeof CREDIT): Promise<void>;
    }
    const usage = { available: true, used_today: 3, daily_limit: 50 };
    await render(['analyst'], false, usage);
    const page = fixture.componentInstance as unknown as AiInbox;
    expect(page.creditColumns()).toContain('ai');

    await page.askAi(CREDIT);

    expect(open).toHaveBeenCalledWith(SuggestionDialog, {
      data: { credit: CREDIT, usage },
      autoFocus: 'dialog',
      width: 'min(720px, 100vw)',
    });
    for (const [roles, closed, available] of [
      [['analyst'], false, false],
      [['analyst'], true, true],
      [['reviewer'], false, true],
    ] as const) {
      TestBed.resetTestingModule();
      await render([...roles], closed, { ...usage, available });
      expect((fixture.componentInstance as unknown as AiInbox).creditColumns()).not.toContain('ai');
    }
  });

  it('names months in Spanish', () => {
    expect(monthLabel('2027-01-01')).toBe('enero de 2027');
  });
});
