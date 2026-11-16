import { HttpErrorResponse } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';

import { LoginView } from '../../api/models/login-view';
import { SessionStore } from '../../core/session/session.store';
import { LoginPage } from './login.page';

const ORGANIZATION = { id: 'org-1', name: 'Comercial Andina', is_demo: false, roles: ['analyst'] };

describe('LoginPage', () => {
  const login = vi.fn<(email: string, password: string) => Promise<LoginView>>();
  let fixture: ComponentFixture<LoginPage>;
  let navigateByUrl: ReturnType<typeof vi.spyOn>;
  let navigate: ReturnType<typeof vi.spyOn>;

  beforeEach(async () => {
    login.mockReset();
    TestBed.configureTestingModule({
      imports: [LoginPage],
      providers: [provideRouter([]), { provide: SessionStore, useValue: { login } }],
    });
    const router = TestBed.inject(Router);
    navigateByUrl = vi.spyOn(router, 'navigateByUrl').mockResolvedValue(true);
    navigate = vi.spyOn(router, 'navigate').mockResolvedValue(true);
    fixture = TestBed.createComponent(LoginPage);
    await fixture.whenStable();
  });

  function element(): HTMLElement {
    return fixture.nativeElement as HTMLElement;
  }

  async function submit(email: string, password: string, volver?: string): Promise<void> {
    if (volver) {
      fixture.componentRef.setInput('volver', volver);
    }
    const input = (name: string) =>
      element().querySelector<HTMLInputElement>(`input[formcontrolname="${name}"]`)!;
    for (const [name, value] of [
      ['email', email],
      ['password', password],
    ]) {
      input(name).value = value;
      input(name).dispatchEvent(new Event('input'));
    }
    element().querySelector('form')!.dispatchEvent(new Event('submit'));
    await fixture.whenStable();
  }

  it('asks for both fields before calling the API', async () => {
    await submit('', '');

    expect(login).not.toHaveBeenCalled();
    expect(element().textContent).toContain('Ingresa tu correo.');
    expect(element().textContent).toContain('Ingresa tu contraseña.');
  });

  it('explains wrong credentials', async () => {
    login.mockRejectedValue(new HttpErrorResponse({ status: 401 }));

    await submit('ana@example.com', 'wrong');

    expect(element().querySelector('[role="alert"]')?.textContent).toContain(
      'El correo o la contraseña no son correctos.',
    );
  });

  it('explains the attempt limit', async () => {
    login.mockRejectedValue(new HttpErrorResponse({ status: 429 }));

    await submit('ana@example.com', 'secret');

    expect(element().querySelector('[role="alert"]')?.textContent).toContain('demasiados intentos');
  });

  it('goes back to the requested page', async () => {
    login.mockResolvedValue({ organization_id: 'org-1', organizations: [ORGANIZATION] });

    await submit('ana@example.com', 'secret', '/conciliacion');

    expect(login).toHaveBeenCalledWith('ana@example.com', 'secret');
    expect(navigateByUrl).toHaveBeenCalledWith('/conciliacion');
  });

  it('never leaves the site after logging in', async () => {
    login.mockResolvedValue({ organization_id: 'org-1', organizations: [ORGANIZATION] });

    await submit('ana@example.com', 'secret', 'https://example.com');

    expect(navigateByUrl).toHaveBeenCalledWith('/');
  });

  it('asks to choose when the user has several organizations', async () => {
    login.mockResolvedValue({
      organization_id: null,
      organizations: [ORGANIZATION, { ...ORGANIZATION, id: 'org-2' }],
    });

    await submit('ana@example.com', 'secret', '/conciliacion');

    expect(navigate).toHaveBeenCalledWith(['/iniciar-sesion/organizacion'], {
      queryParams: { volver: '/conciliacion' },
    });
  });
});
