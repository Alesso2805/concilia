import { HttpErrorResponse } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';

import { OpenReceivableView } from '../../api/models/open-receivable-view';
import { provideLocale } from '../../core/locale';
import { ManualPage } from './manual.page';
import { MatchingService } from './matching.service';

const CREDIT = {
  id: 'c1',
  booked_on: '2027-01-12',
  description: 'PAGO A CUENTA F001-200',
  operation_number: null,
  amount_cents: 40_000,
};
const RECEIVABLE: OpenReceivableView = {
  id: 'r1',
  doc_number: 'F001-200',
  customer_name: 'Comercial Andina SAC',
  customer_tax_id: null,
  issued_on: '2027-01-02',
  due_on: '2027-01-31',
  amount_cents: 100_000,
  available_cents: 100_000,
};
const PAGE = { has_previous: false, has_next: false, previous_cursor: null, next_cursor: null };

describe('ManualPage', () => {
  let fixture: ComponentFixture<ManualPage>;
  let service: Record<string, ReturnType<typeof vi.fn>>;
  let navigate: ReturnType<typeof vi.spyOn>;

  async function render(): Promise<HTMLElement> {
    service = {
      credits: vi.fn(() => Promise.resolve({ credits: [CREDIT], ...PAGE })),
      openReceivables: vi.fn(() => Promise.resolve({ receivables: [RECEIVABLE], ...PAGE })),
      createManual: vi.fn(() => Promise.resolve({ id: 'm1', status: 'confirmed' })),
    };
    TestBed.configureTestingModule({
      imports: [ManualPage],
      providers: [
        provideRouter([]),
        provideLocale(),
        { provide: MatchingService, useValue: service },
      ],
    });
    navigate = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    fixture = TestBed.createComponent(ManualPage);
    fixture.componentRef.setInput('cuenta', 'a1');
    fixture.componentRef.setInput('mes', '2027-01-01');
    await settle();
    return fixture.nativeElement as HTMLElement;
  }

  async function settle(): Promise<void> {
    await fixture.whenStable();
    await new Promise((resolve) => setTimeout(resolve));
    await fixture.whenStable();
  }

  function button(element: HTMLElement, label: string): HTMLButtonElement {
    return [...element.querySelectorAll('button')].find(
      (candidate) => candidate.textContent?.trim() === label,
    )!;
  }

  function text(): string {
    return ((fixture.nativeElement as HTMLElement).textContent ?? '').replace(/\s+/g, ' ');
  }

  async function pickAndAdd(element: HTMLElement): Promise<HTMLInputElement> {
    element.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click();
    button(element, 'Agregar').click();
    await settle();
    return element.querySelector<HTMLInputElement>('input[inputmode="decimal"]')!;
  }

  it('applies a partial payment and confirms it', async () => {
    const element = await render();
    const amount = await pickAndAdd(element);

    expect(amount.value).toBe('1000.00');
    expect(text()).toContain('DiferenciaS/ -600.00');
    amount.value = '400';
    amount.dispatchEvent(new Event('input'));
    await settle();
    expect(text()).toContain('DiferenciaS/ 0.00');
    expect(text()).toContain('Parcial');

    button(element, 'Confirmar conciliación').click();
    await settle();

    expect(service['createManual']).toHaveBeenCalledWith(
      { accountId: 'a1', period: '2027-01-01' },
      {
        creditIds: ['c1'],
        applications: [{ receivableId: 'r1', appliedCents: 40_000 }],
        differenceReason: null,
        differenceNote: null,
      },
    );
    expect(navigate).toHaveBeenCalledWith(['/bandeja'], {
      queryParams: { cuenta: 'a1', mes: '2027-01-01' },
    });
  });

  it('does not save an amount above the balance', async () => {
    const element = await render();
    const amount = await pickAndAdd(element);

    amount.value = '1000.01';
    amount.dispatchEvent(new Event('input'));
    await settle();

    expect(text()).toContain('no superar el saldo del cobro');
    expect(button(element, 'Confirmar conciliación').disabled).toBe(true);
  });

  it('explains a refusal from the server', async () => {
    const element = await render();
    await pickAndAdd(element);
    service['createManual'].mockRejectedValue(
      new HttpErrorResponse({ status: 409, error: { detail: 'credit_not_free' } }),
    );

    button(element, 'Confirmar conciliación').click();
    await settle();

    expect(element.querySelector('[role="alert"]')?.textContent).toContain(
      'Algún abono ya está en otra conciliación',
    );
    expect(navigate).not.toHaveBeenCalled();
  });
});
