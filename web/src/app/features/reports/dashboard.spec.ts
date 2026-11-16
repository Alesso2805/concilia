import { Component, input } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { DashboardView } from '../../api/models/dashboard-view';
import { provideLocale } from '../../core/locale';
import { BankingService } from '../admin/banking.service';
import { ChartCard } from './chart-card.component';
import { ChartRow } from './charts';
import { DashboardPage } from './dashboard.page';
import { ReportsService } from './reports.service';

@Component({ selector: 'app-chart-card', template: '' })
class ChartStub {
  readonly heading = input.required<string>();
  readonly category = input.required<string>();
  readonly rows = input.required<readonly ChartRow[]>();
  readonly empty = input('');
}

const VIEW: DashboardView = {
  period: '2027-01-01',
  reference_date: '2027-01-31',
  closed: true,
  credits: {
    free: { count: 1, cents: 25_000 },
    proposed: { count: 0, cents: 0 },
    confirmed: { count: 0, cents: 0 },
    approved: { count: 2, cents: 75_000 },
  },
  pending: [
    { bucket: '0-7', count: 1, cents: 25_000 },
    { bucket: '8-30', count: 0, cents: 0 },
    { bucket: '31+', count: 0, cents: 0 },
  ],
  differences: [{ reason: 'commission', count: 1, cents: 500 }],
};

async function settle(fixture: ComponentFixture<unknown>): Promise<void> {
  for (let round = 0; round < 3; round++) {
    await fixture.whenStable();
    await new Promise((resolve) => setTimeout(resolve));
  }
}

describe('DashboardPage', () => {
  let fixture: ComponentFixture<DashboardPage>;
  let reports: Record<string, ReturnType<typeof vi.fn>>;

  beforeEach(async () => {
    reports = {
      periods: vi.fn(() => Promise.resolve([{ period: '2027-01-01', closed: true, credits: 3 }])),
      dashboard: vi.fn(() => Promise.resolve(VIEW)),
    };
    TestBed.configureTestingModule({
      imports: [DashboardPage],
      providers: [
        provideLocale(),
        { provide: ReportsService, useValue: reports },
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
      ],
    }).overrideComponent(DashboardPage, {
      remove: { imports: [ChartCard] },
      add: { imports: [ChartStub] },
    });
    fixture = TestBed.createComponent(DashboardPage);
    await settle(fixture);
  });

  function charts(): { heading: string; rows: readonly ChartRow[] }[] {
    return fixture.debugElement
      .queryAll((node) => node.componentInstance instanceof ChartStub)
      .map((node) => {
        const chart = node.componentInstance as ChartStub;
        return { heading: chart.heading(), rows: chart.rows() };
      });
  }

  it('shows the reconciled share by amount and by count for the newest month', () => {
    const text = (fixture.nativeElement as HTMLElement).textContent!.replace(/\s+/g, ' ');

    expect(reports['dashboard']).toHaveBeenCalledWith({ accountId: 'a1', period: '2027-01-01' });
    const figures = [
      ...(fixture.nativeElement as HTMLElement).querySelectorAll('.reports__figure'),
    ].map((figure) => [
      figure.querySelector('dt')!.textContent!.trim(),
      figure.querySelector('dd')!.textContent!.trim(),
    ]);
    expect(figures).toEqual([
      ['Conciliado por monto', '75.0 %'],
      ['Conciliado por cantidad', '66.6 %'],
      ['Abonos del mes', '3'],
    ]);
    expect(text).toContain('enero de 2027 (cerrado)');
    expect(text).toContain('se mide al 31/01/2027');
  });

  it('charts credits by status, pending by age and differences by reason', () => {
    expect(charts()).toEqual([
      {
        heading: 'Abonos del mes por estado',
        rows: [
          { label: 'Conciliados', count: 2, cents: 75_000 },
          { label: 'Confirmados', count: 0, cents: 0 },
          { label: 'Propuestos', count: 0, cents: 0 },
          { label: 'Sin conciliar', count: 1, cents: 25_000 },
        ],
      },
      {
        heading: 'Pendientes por antigüedad',
        rows: [
          { label: '0 a 7 días', bucket: '0-7', count: 1, cents: 25_000 },
          { label: '8 a 30 días', bucket: '8-30', count: 0, cents: 0 },
          { label: 'Más de 30 días', bucket: '31+', count: 0, cents: 0 },
        ],
      },
      { heading: 'Diferencias por motivo', rows: [{ label: 'Comisión', count: 1, cents: 500 }] },
    ]);
  });
});
