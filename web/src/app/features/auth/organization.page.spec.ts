import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';

import { SessionView } from '../../api/models/session-view';
import { SessionStore } from '../../core/session/session.store';
import { OrganizationPage } from './organization.page';

const SESSION: SessionView = {
  user_id: 'user-1',
  organization_id: null,
  roles: [],
  organizations: [
    { id: 'org-1', name: 'Comercial Andina', is_demo: false, roles: ['admin', 'reviewer'] },
    { id: 'org-2', name: 'Demo', is_demo: true, roles: ['analyst'] },
  ],
};

describe('OrganizationPage', () => {
  const chooseOrganization = vi.fn<(id: string) => Promise<void>>();
  let fixture: ComponentFixture<OrganizationPage>;
  let navigateByUrl: ReturnType<typeof vi.spyOn>;

  beforeEach(async () => {
    chooseOrganization.mockReset();
    TestBed.configureTestingModule({
      imports: [OrganizationPage],
      providers: [
        provideRouter([]),
        { provide: SessionStore, useValue: { session: signal(SESSION), chooseOrganization } },
      ],
    });
    navigateByUrl = vi.spyOn(TestBed.inject(Router), 'navigateByUrl').mockResolvedValue(true);
    fixture = TestBed.createComponent(OrganizationPage);
    fixture.componentRef.setInput('volver', '/conciliacion');
    await fixture.whenStable();
  });

  function buttons(): HTMLButtonElement[] {
    return [...(fixture.nativeElement as HTMLElement).querySelectorAll('button')];
  }

  it('lists the organizations with their roles', () => {
    expect(buttons().map((button) => button.textContent?.replace(/\s+/g, ' ').trim())).toEqual([
      'Comercial Andina Administración, Revisión',
      'Demo Demo · Análisis',
    ]);
  });

  it('opens the chosen organization and goes back', async () => {
    chooseOrganization.mockResolvedValue();

    buttons()[1].click();
    await fixture.whenStable();

    expect(chooseOrganization).toHaveBeenCalledWith('org-2');
    expect(navigateByUrl).toHaveBeenCalledWith('/conciliacion');
  });

  it('explains a failure', async () => {
    chooseOrganization.mockRejectedValue(new Error('offline'));

    buttons()[0].click();
    await fixture.whenStable();

    expect(
      (fixture.nativeElement as HTMLElement).querySelector('[role="alert"]')?.textContent,
    ).toContain('No pudimos abrir esa organización.');
    expect(navigateByUrl).not.toHaveBeenCalled();
  });
});
