import { ComponentFixture, TestBed } from '@angular/core/testing';

import { ChartCard } from './chart-card.component';
import { ChartRow } from './charts';

class NoResize {
  readonly observe = vi.fn();
  readonly unobserve = vi.fn();
  readonly disconnect = vi.fn();
}

describe('ChartCard', () => {
  let fixture: ComponentFixture<ChartCard>;

  beforeAll(() => {
    globalThis.ResizeObserver ??= NoResize as unknown as typeof ResizeObserver;
  });

  async function render(rows: ChartRow[]): Promise<HTMLElement> {
    TestBed.configureTestingModule({ imports: [ChartCard] });
    fixture = TestBed.createComponent(ChartCard);
    fixture.componentRef.setInput('heading', 'Pendientes por antigüedad');
    fixture.componentRef.setInput('category', 'Antigüedad');
    fixture.componentRef.setInput('rows', rows);
    fixture.componentRef.setInput('empty', 'No hay abonos pendientes.');
    await fixture.whenStable();
    return fixture.nativeElement as HTMLElement;
  }

  it('says when there is nothing to chart', async () => {
    const element = await render([]);

    expect(element.textContent).toContain('No hay abonos pendientes.');
    expect(element.querySelector('button')).toBeNull();
  });

  it('labels the chart and shows the same data as a table', async () => {
    const element = await render([{ label: '0 a 7 días', count: 2, cents: 15_000 }]);
    const chart = element.querySelector('[role="img"]')!;
    expect(chart.getAttribute('aria-label')).toContain('0 a 7 días: S/ 150.00, 2 abonos');

    const toggle = element.querySelector('button')!;
    toggle.click();
    await fixture.whenStable();

    expect(toggle.getAttribute('aria-pressed')).toBe('true');
    expect(toggle.textContent?.trim()).toBe('Ver como gráfico');
    const cells = [...element.querySelectorAll('tbody th, tbody td')].map((cell) =>
      cell.textContent?.trim(),
    );
    expect(cells).toEqual(['0 a 7 días', '2', 'S/ 150.00']);
    expect(element.querySelector('section')!.getAttribute('aria-labelledby')).toBe(
      element.querySelector('h2')!.id,
    );
  });
});
