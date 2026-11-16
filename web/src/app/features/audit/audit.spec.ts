import { HttpErrorResponse } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { AuditEventView } from '../../api/models/audit-event-view';
import { provideLocale } from '../../core/locale';
import { AuditPage } from './audit.page';
import { AuditService, NO_AUDIT_FILTERS } from './audit.service';
import { metadataSummary } from './labels';

const EVENT: AuditEventView = {
  id: 'e1',
  at: '2027-01-05T04:30:00Z',
  actor_user_id: 'u1',
  actor_name: 'Ana Revisora',
  action: 'period.closed',
  entity: 'period_event',
  entity_id: 'p1',
  metadata: {},
};
const PAGE = { has_previous: false, has_next: true, previous_cursor: '9', next_cursor: '8' };

async function settle(fixture: ComponentFixture<unknown>): Promise<void> {
  for (let round = 0; round < 3; round++) {
    await fixture.whenStable();
    await new Promise((resolve) => setTimeout(resolve));
  }
}

function text(fixture: ComponentFixture<unknown>): string {
  return ((fixture.nativeElement as HTMLElement).textContent ?? '').replace(/\s+/g, ' ');
}

describe('AuditPage', () => {
  let fixture: ComponentFixture<AuditPage>;
  let service: Record<string, ReturnType<typeof vi.fn>>;

  async function render(): Promise<HTMLElement> {
    service = {
      actors: vi.fn(() => Promise.resolve([{ user_id: 'u1', display_name: 'Ana Revisora' }])),
      events: vi.fn(() => Promise.resolve({ events: [EVENT], ...PAGE })),
    };
    TestBed.configureTestingModule({
      imports: [AuditPage],
      providers: [provideLocale(), { provide: AuditService, useValue: service }],
    });
    fixture = TestBed.createComponent(AuditPage);
    await settle(fixture);
    return fixture.nativeElement as HTMLElement;
  }

  it('lists the newest events with their Lima time and labels', async () => {
    await render();

    expect(service['events']).toHaveBeenCalledWith(NO_AUDIT_FILTERS, {});
    expect(text(fixture)).toContain('04/01/2027 23:30');
    expect(text(fixture)).toContain('Ana Revisora');
    expect(text(fixture)).toContain('Cerró un mes');
    expect(text(fixture)).toContain('Cierre de mes');
  });

  it('filters by person, action, entity and dates from the first page', async () => {
    const element = await render();
    const page = fixture.componentInstance as unknown as {
      form: { patchValue(value: object): void };
    };

    page.form.patchValue({
      actorUserId: 'u1',
      action: 'match.approved',
      entity: 'match',
      from: '2027-01-01',
      to: '2027-01-31',
    });
    element.querySelector('form')!.dispatchEvent(new Event('submit'));
    await settle(fixture);

    expect(service['events']).toHaveBeenLastCalledWith(
      {
        actorUserId: 'u1',
        action: 'match.approved',
        entity: 'match',
        from: '2027-01-01',
        to: '2027-01-31',
      },
      {},
    );
  });

  it('explains an inverted date range', async () => {
    const element = await render();
    service['events'].mockRejectedValue(
      new HttpErrorResponse({ status: 422, error: { detail: 'invalid_range' } }),
    );

    element.querySelector('form')!.dispatchEvent(new Event('submit'));
    await settle(fixture);

    expect(text(fixture)).toContain('La fecha «desde» debe ser anterior o igual');
  });

  it('summarizes the allowed metadata keys in Spanish', () => {
    expect(metadataSummary({ source: 'cli' })).toBe('Origen: consola');
    expect(metadataSummary({ roles: ['analyst', 'reviewer'] })).toBe('Roles: Análisis, Revisión');
    expect(metadataSummary({ kind: 'receivables', fields: ['tolerance_bp'] })).toBe(
      'Tipo: cobros · Campos: tolerance_bp',
    );
    expect(metadataSummary({})).toBe('—');
  });
});
