import { Location } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router, provideRouter } from '@angular/router';

import { SessionView } from '../../api/models/session-view';
import { SessionStore } from '../../core/session/session.store';
import { InvitationPage } from './invitation.page';
import { InvitationService } from './invitation.service';

const SESSION: SessionView = { user_id: 'u', organization_id: null, organizations: [], roles: [] };

describe('InvitationPage', () => {
  let fixture: ComponentFixture<InvitationPage>;
  let store: Record<string, ReturnType<typeof vi.fn>>;
  let invitations: Record<string, ReturnType<typeof vi.fn>>;
  let navigateByUrl: ReturnType<typeof vi.spyOn>;
  let replaceState: ReturnType<typeof vi.spyOn>;

  async function render(
    fragment: string | null,
    session: SessionView | null,
  ): Promise<HTMLElement> {
    store = {
      restore: vi.fn(() => Promise.resolve(session)),
      refresh: vi.fn(() => Promise.resolve(session)),
      chooseOrganization: vi.fn(() => Promise.resolve()),
    };
    invitations = {
      acceptAsMember: vi.fn(() => Promise.resolve('org-1')),
      acceptWithNewAccount: vi.fn(() => Promise.resolve()),
    };
    TestBed.configureTestingModule({
      imports: [InvitationPage],
      providers: [
        provideRouter([]),
        { provide: ActivatedRoute, useValue: { snapshot: { fragment } } },
        { provide: SessionStore, useValue: store },
        { provide: InvitationService, useValue: invitations },
      ],
    });
    navigateByUrl = vi.spyOn(TestBed.inject(Router), 'navigateByUrl').mockResolvedValue(true);
    replaceState = vi.spyOn(TestBed.inject(Location), 'replaceState');
    fixture = TestBed.createComponent(InvitationPage);
    await settle();
    return fixture.nativeElement as HTMLElement;
  }

  async function settle(): Promise<void> {
    await fixture.whenStable();
    await new Promise((resolve) => setTimeout(resolve));
    await fixture.whenStable();
  }

  function fill(element: HTMLElement, values: Record<string, string>): void {
    for (const [name, value] of Object.entries(values)) {
      const input = element.querySelector<HTMLInputElement>(`input[formcontrolname="${name}"]`)!;
      input.value = value;
      input.dispatchEvent(new Event('input'));
    }
  }

  beforeEach(() => sessionStorage.clear());

  it('explains a link without a token', async () => {
    const element = await render(null, null);

    expect(element.textContent).toContain('Este enlace de invitación no es válido.');
  });

  it('keeps the token out of the address bar and creates the account', async () => {
    const element = await render('secret-token', null);

    expect(replaceState).toHaveBeenCalledWith('/invitacion');
    fill(element, {
      email: 'luis@example.test',
      display_name: 'Luis',
      password: 'una clave larga',
    });
    element.querySelector('form')!.dispatchEvent(new Event('submit'));
    await settle();

    expect(invitations['acceptWithNewAccount']).toHaveBeenCalledWith('secret-token', {
      email: 'luis@example.test',
      display_name: 'Luis',
      password: 'una clave larga',
    });
    expect(store['refresh']).toHaveBeenCalled();
    expect(navigateByUrl).toHaveBeenCalledWith('/');
    expect(sessionStorage.getItem('concilia.invitation')).toBeNull();
  });

  it('asks for a long enough password before calling the API', async () => {
    const element = await render('secret-token', null);

    fill(element, { email: 'luis@example.test', display_name: 'Luis', password: 'corta' });
    element.querySelector('form')!.dispatchEvent(new Event('submit'));
    await settle();

    expect(invitations['acceptWithNewAccount']).not.toHaveBeenCalled();
    expect(element.textContent).toContain('La contraseña debe tener al menos 12 caracteres.');
  });

  it('gives one explanation for an invitation that cannot be used', async () => {
    const element = await render('secret-token', null);
    invitations['acceptWithNewAccount'].mockImplementation(() =>
      Promise.reject(
        new HttpErrorResponse({ status: 409, error: { detail: 'invitation_not_valid' } }),
      ),
    );

    fill(element, {
      email: 'luis@example.test',
      display_name: 'Luis',
      password: 'una clave larga',
    });
    element.querySelector('form')!.dispatchEvent(new Event('submit'));
    await settle();

    expect(element.querySelector('[role="alert"]')?.textContent).toContain(
      'Si ya tienes una cuenta, inicia sesión para aceptarla.',
    );
    expect(sessionStorage.getItem('concilia.invitation')).toBe('secret-token');
  });

  it('lets a signed-in user accept with the token kept across the login', async () => {
    sessionStorage.setItem('concilia.invitation', 'kept-token');
    const element = await render(null, SESSION);

    element.querySelector('button')!.click();
    await settle();

    expect(invitations['acceptAsMember']).toHaveBeenCalledWith('kept-token');
    expect(store['chooseOrganization']).toHaveBeenCalledWith('org-1');
    expect(navigateByUrl).toHaveBeenCalledWith('/');
  });
});
