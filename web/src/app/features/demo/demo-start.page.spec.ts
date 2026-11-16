import { HttpErrorResponse } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';

import { SessionStore } from '../../core/session/session.store';
import { DemoStartPage } from './demo-start.page';

describe('DemoStartPage', () => {
  async function render(startDemo: () => Promise<void>): Promise<HTMLElement> {
    TestBed.configureTestingModule({
      imports: [DemoStartPage],
      providers: [provideRouter([]), { provide: SessionStore, useValue: { startDemo } }],
    });
    const navigate = vi.spyOn(TestBed.inject(Router), 'navigateByUrl').mockResolvedValue(true);
    const fixture = TestBed.createComponent(DemoStartPage);
    await fixture.whenStable();
    await new Promise((resolve) => setTimeout(resolve));
    await fixture.whenStable();
    navigateCalls = navigate.mock.calls;
    return fixture.nativeElement as HTMLElement;
  }

  let navigateCalls: unknown[][] = [];

  it('creates a demo and opens its inbox', async () => {
    const startDemo = vi.fn(() => Promise.resolve());

    await render(startDemo);

    expect(startDemo).toHaveBeenCalled();
    expect(navigateCalls).toEqual([['/bandeja']]);
  });

  it('explains why a demo could not be created', async () => {
    const element = await render(() => Promise.reject(new HttpErrorResponse({ status: 429 })));

    expect(element.querySelector('[role="alert"]')?.textContent).toContain(
      'Hoy ya se crearon muchas demos',
    );
    expect(element.textContent).toContain('Ir al inicio de sesión');
  });
});
