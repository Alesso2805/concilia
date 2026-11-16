import { HttpErrorResponse } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MatDialog } from '@angular/material/dialog';
import { of } from 'rxjs';

import { TeamView } from '../../api/models/team-view';
import { provideIcons } from '../../core/icons';
import { provideLocale } from '../../core/locale';
import { RemovalDialog, RolesDialog } from './member.dialogs';
import { TeamPage } from './team.page';
import { TeamService } from './team.service';

const TEAM: TeamView = {
  members: [
    {
      user_id: 'u1',
      display_name: 'Ana Torres',
      email: 'ana@example.test',
      roles: ['admin', 'reviewer'],
      joined_at: '2026-11-01T10:00:00Z',
    },
  ],
  invitations: [
    {
      id: 'i1',
      email: 'luis@example.test',
      roles: ['analyst'],
      created_at: '2026-11-20T10:00:00Z',
      expires_at: '2026-11-27T10:00:00Z',
    },
  ],
};

describe('TeamPage', () => {
  let fixture: ComponentFixture<TeamPage>;
  let service: { load: ReturnType<typeof vi.fn>; revoke: ReturnType<typeof vi.fn> };
  let open: ReturnType<typeof vi.fn>;

  async function render(load: () => Promise<TeamView>): Promise<HTMLElement> {
    service = { load: vi.fn(load), revoke: vi.fn(() => Promise.resolve()) };
    open = vi.fn(() => ({ afterClosed: () => of(true) }));
    TestBed.configureTestingModule({
      imports: [TeamPage],
      providers: [
        provideIcons(),
        provideLocale(),
        { provide: TeamService, useValue: service },
        { provide: MatDialog, useValue: { open } },
      ],
    });
    fixture = TestBed.createComponent(TeamPage);
    await fixture.whenStable();
    return fixture.nativeElement as HTMLElement;
  }

  function rows(element: HTMLElement, section: string): string[] {
    const selector = `section[aria-labelledby="${section}"] tr.mat-mdc-row`;
    return [...element.querySelectorAll(selector)].map((row) =>
      [...row.querySelectorAll('td')]
        .map((cell) => cell.textContent?.trim())
        .filter(Boolean)
        .join(' | '),
    );
  }

  it('lists members and pending invitations', async () => {
    const element = await render(() => Promise.resolve(TEAM));

    expect(rows(element, 'miembros')).toEqual([
      'Ana Torres | ana@example.test | Administración, Revisión',
    ]);
    expect(rows(element, 'invitaciones')).toEqual([
      'luis@example.test | Análisis | 27 nov. 2026 | Revocar',
    ]);
  });

  it('says when there are no pending invitations', async () => {
    const element = await render(() => Promise.resolve({ ...TEAM, invitations: [] }));

    expect(element.textContent).toContain('No hay invitaciones pendientes.');
  });

  it('revokes an invitation and reloads', async () => {
    const element = await render(() => Promise.resolve(TEAM));

    element
      .querySelector<HTMLButtonElement>('[aria-label="Revocar la invitación a luis@example.test"]')!
      .click();
    await fixture.whenStable();

    expect(service.revoke).toHaveBeenCalledWith('i1');
    expect(service.load).toHaveBeenCalledTimes(2);
  });

  it('opens the member dialogs with the member and reloads after a change', async () => {
    const element = await render(() => Promise.resolve(TEAM));

    element
      .querySelector<HTMLButtonElement>('[aria-label="Editar los roles de Ana Torres"]')!
      .click();
    await fixture.whenStable();
    element.querySelector<HTMLButtonElement>('[aria-label="Dar de baja a Ana Torres"]')!.click();
    await fixture.whenStable();

    expect(open.mock.calls.map(([component, config]) => [component, config.data])).toEqual([
      [RolesDialog, TEAM.members[0]],
      [RemovalDialog, TEAM.members[0]],
    ]);
    expect(service.load).toHaveBeenCalledTimes(3);
  });

  it('explains a failure to load', async () => {
    const element = await render(() =>
      Promise.reject(new HttpErrorResponse({ status: 500, error: { detail: 'boom' } })),
    );

    expect(element.querySelector('[role="alert"]')?.textContent).toContain(
      'No pudimos completar la operación.',
    );
  });
});
