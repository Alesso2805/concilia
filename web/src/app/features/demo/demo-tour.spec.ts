import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { DemoTour, TOUR_STEPS } from './demo-tour.component';

describe('DemoTour', () => {
  let fixture: ComponentFixture<DemoTour>;

  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  async function render(): Promise<HTMLElement> {
    TestBed.configureTestingModule({ imports: [DemoTour], providers: [provideRouter([])] });
    fixture = TestBed.createComponent(DemoTour);
    fixture.componentRef.setInput('organizationId', 'org-1');
    await fixture.whenStable();
    return fixture.nativeElement as HTMLElement;
  }

  function button(element: HTMLElement, label: string): HTMLButtonElement {
    return [...element.querySelectorAll('button')].find(
      (candidate) => candidate.textContent?.trim() === label,
    )!;
  }

  it('always says the data is fictitious and opens the tour on request', async () => {
    const element = await render();
    expect(element.textContent).toContain('Demo con datos ficticios');
    expect(element.querySelector('#recorrido')).toBeNull();

    const toggle = button(element, 'Recorrido guiado');
    toggle.click();
    await fixture.whenStable();

    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    expect(element.querySelector('h2')!.textContent).toContain(`paso 1 de ${TOUR_STEPS.length}`);
    expect(element.querySelector('[aria-current="step"]')!.textContent).toContain(
      'Importa el tercer mes',
    );
    expect(element.querySelector('a')!.getAttribute('href')).toBe('/importaciones');
  });

  it('walks the steps and remembers where the visitor is', async () => {
    const element = await render();
    button(element, 'Recorrido guiado').click();
    await fixture.whenStable();

    button(element, 'Siguiente').click();
    button(element, 'Siguiente').click();
    await fixture.whenStable();

    expect(element.querySelector('[aria-current="step"]')!.textContent).toContain(
      'Confirma propuestas',
    );
    expect(localStorage.getItem('concilia.tour.org-1')).toBe('2');
    TestBed.resetTestingModule();

    const again = await render();
    button(again, 'Recorrido guiado').click();
    await fixture.whenStable();
    expect(again.querySelector('h2')!.textContent).toContain('paso 3');
  });

  it('starts at the first step when the browser refuses storage', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    const element = await render();
    button(element, 'Recorrido guiado').click();
    await fixture.whenStable();

    button(element, 'Siguiente').click();
    await fixture.whenStable();

    expect(element.querySelector('h2')!.textContent).toContain('paso 2');
  });
});
