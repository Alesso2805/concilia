import { computed, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';

import { SessionView } from '../../api/models/session-view';
import { provideIcons } from '../icons';
import { SessionStore } from '../session/session.store';
import { ShellComponent } from './shell.component';

const ANDINA = { id: 'org-1', name: 'Comercial Andina', is_demo: false, roles: ['analyst'] };
const DEMO = { id: 'org-2', name: 'Demo Lima', is_demo: true, roles: ['analyst'] };

function sessionIn(organization: typeof ANDINA, others: (typeof ANDINA)[] = []): SessionView {
  return {
    user_id: 'user-1',
    organization_id: organization.id,
    organizations: [organization, ...others],
    roles: organization.roles,
  };
}

describe('ShellComponent', () => {
  let fixture: ComponentFixture<ShellComponent>;

  async function render(
    session: SessionView,
    logout: () => Promise<void> = () => Promise.resolve(),
  ): Promise<HTMLElement> {
    const state = signal(session);
    TestBed.configureTestingModule({
      imports: [ShellComponent],
      providers: [
        provideRouter([]),
        provideIcons(),
        {
          provide: SessionStore,
          useValue: {
            session: state,
            organization: computed(() =>
              state().organizations.find((o) => o.id === state().organization_id),
            ),
            roles: computed(() => new Set(state().roles)),
            logout,
          },
        },
      ],
    });
    fixture = TestBed.createComponent(ShellComponent);
    await fixture.whenStable();
    return fixture.nativeElement as HTMLElement;
  }

  async function openAccountMenu(): Promise<HTMLElement> {
    (fixture.nativeElement as HTMLElement)
      .querySelector<HTMLButtonElement>('button[aria-label="Cuenta"]')!
      .click();
    await fixture.whenStable();
    return document.querySelector('.mat-mdc-menu-panel')!;
  }

  it('shows the organization, a skip link and the navigation for the roles', async () => {
    const element = await render(sessionIn(ANDINA));

    expect(element.querySelector('.shell__organization')?.textContent).toBe('Comercial Andina');
    expect(element.querySelector('.shell__badge')).toBeNull();
    expect(element.querySelector('a.skip-link')?.getAttribute('href')).toBe('#contenido');
    expect(element.querySelector('main#contenido')).not.toBeNull();
    expect([...element.querySelectorAll('nav a')].map((a) => a.textContent?.trim())).toEqual([
      'Inicio',
      'Importaciones',
    ]);
  });

  it('marks a demo organization', async () => {
    const element = await render(sessionIn(DEMO));

    expect(element.querySelector('.shell__badge')?.textContent).toBe('Demo');
  });

  it('offers to switch only with several organizations', async () => {
    await render(sessionIn(ANDINA));
    expect((await openAccountMenu()).textContent).not.toContain('Cambiar de organización');
  });

  it('offers to switch with several organizations', async () => {
    await render(sessionIn(ANDINA, [DEMO]));
    expect((await openAccountMenu()).textContent).toContain('Cambiar de organización');
  });

  it('logs out and goes to the login even if the server fails', async () => {
    const logout = vi.fn(() => Promise.reject(new Error('offline')));
    await render(sessionIn(ANDINA), logout);
    const navigate = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);

    const menu = await openAccountMenu();
    [...menu.querySelectorAll('button')]
      .find((b) => b.textContent?.includes('Cerrar sesión'))!
      .click();
    await fixture.whenStable();

    expect(logout).toHaveBeenCalled();
    expect(navigate).toHaveBeenCalledWith(['/iniciar-sesion']);
  });
});
