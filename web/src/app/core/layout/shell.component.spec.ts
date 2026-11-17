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
    switchDemoRole: (role: string) => Promise<void> = () => Promise.resolve(),
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
            switchDemoRole,
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

    expect(element.querySelector('.shell__organization-name')?.textContent).toBe(
      'Comercial Andina',
    );
    expect(element.querySelector('.shell__badge')).toBeNull();
    expect(element.querySelector('a.skip-link')?.getAttribute('href')).toBe('#contenido');
    expect(element.querySelector('main#contenido')).not.toBeNull();
    expect([...element.querySelectorAll('nav a')].map((a) => a.textContent?.trim())).toEqual([
      'Inicio',
      'Bandeja',
      'Panel',
      'Importaciones',
      'Cobros',
      'Auditoría',
    ]);
    expect(
      [...element.querySelectorAll('.shell__section')].map((label) => label.textContent?.trim()),
    ).toEqual(['Conciliación', 'Control']);
  });

  it('names the current page and its section in the toolbar', async () => {
    const element = await render(sessionIn(ANDINA));
    await TestBed.inject(Router).navigateByUrl('/');
    await fixture.whenStable();

    expect(
      [...element.querySelectorAll('.shell__trail span')].map((part) => part.textContent?.trim()),
    ).toEqual(['Conciliación', '/', 'Inicio']);
  });

  it('lets a demo visitor switch role and offers it nowhere else', async () => {
    const switchDemoRole = vi.fn(() => Promise.resolve());
    const element = await render(sessionIn(DEMO), undefined, switchDemoRole);
    const navigate = vi.spyOn(TestBed.inject(Router), 'navigateByUrl').mockResolvedValue(true);
    const toggle = [...element.querySelectorAll('button')].find((button) =>
      button.textContent?.includes('Ver como: Análisis'),
    )!;

    toggle.click();
    await fixture.whenStable();
    [...document.querySelectorAll<HTMLButtonElement>('.mat-mdc-menu-panel button')]
      .find((button) => button.textContent?.trim() === 'Revisión')!
      .click();
    await fixture.whenStable();

    expect(switchDemoRole).toHaveBeenCalledWith('reviewer');
    expect(navigate).toHaveBeenCalledWith('/bandeja');
  });

  it('shows no role switch outside a demo', async () => {
    const element = await render(sessionIn(ANDINA));

    expect(element.textContent).not.toContain('Ver como');
  });

  it('marks a demo organization and says its data is fictitious', async () => {
    const element = await render(sessionIn(DEMO));
    await fixture.whenStable();

    expect(element.querySelector('.shell__badge')?.textContent).toBe('Demo');
    expect(element.textContent).toContain('Demo con datos ficticios');
  });

  it('shows no fictitious data notice outside a demo', async () => {
    const element = await render(sessionIn(ANDINA));
    await fixture.whenStable();

    expect(element.textContent).not.toContain('Demo con datos ficticios');
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
