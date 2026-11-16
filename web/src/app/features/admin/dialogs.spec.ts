import { HttpErrorResponse } from '@angular/common/http';
import { Type } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';

import { MemberView } from '../../api/models/member-view';
import { provideIcons } from '../../core/icons';
import { InviteDialog } from './invite.dialog';
import { RemovalDialog, RolesDialog } from './member.dialogs';
import { roleGroup, selectedRoles } from './role-picker';
import { TeamService } from './team.service';

const MEMBER: MemberView = {
  user_id: 'u1',
  display_name: 'Ana Torres',
  email: 'ana@example.test',
  roles: ['admin'],
  joined_at: '2026-11-01T10:00:00Z',
};

function conflict(detail: string): HttpErrorResponse {
  return new HttpErrorResponse({ status: 409, error: { detail } });
}

function setup<T>(
  component: Type<T>,
  team: Partial<Record<keyof TeamService, unknown>>,
): { fixture: ComponentFixture<T>; close: ReturnType<typeof vi.fn> } {
  const close = vi.fn();
  TestBed.configureTestingModule({
    imports: [component],
    providers: [
      provideIcons(),
      { provide: TeamService, useValue: team },
      { provide: MatDialogRef, useValue: { close } },
      { provide: MAT_DIALOG_DATA, useValue: MEMBER },
    ],
  });
  return { fixture: TestBed.createComponent(component), close };
}

function text(fixture: ComponentFixture<unknown>): string {
  return (fixture.nativeElement as HTMLElement).textContent ?? '';
}

async function submit(fixture: ComponentFixture<unknown>): Promise<void> {
  (fixture.nativeElement as HTMLElement).querySelector('form')!.dispatchEvent(new Event('submit'));
  await fixture.whenStable();
}

describe('role picker helpers', () => {
  it('reads the selected roles and needs at least one', () => {
    const group = roleGroup(['reviewer']);
    expect(selectedRoles(group)).toEqual(['reviewer']);

    group.setValue({ admin: false, analyst: false, reviewer: false });
    expect(group.hasError('roles')).toBe(true);
  });
});

describe('InviteDialog', () => {
  async function fill(fixture: ComponentFixture<InviteDialog>, email: string): Promise<void> {
    await fixture.whenStable();
    const input = (fixture.nativeElement as HTMLElement).querySelector<HTMLInputElement>(
      'input[formcontrolname="email"]',
    )!;
    input.value = email;
    input.dispatchEvent(new Event('input'));
  }

  it('shows the single-use link once the invitation exists', async () => {
    const invite = vi.fn(() => Promise.resolve({ token: 'secret-token', invitation: {} }));
    const { fixture } = setup(InviteDialog, { invite });

    await fill(fixture, 'luis@example.test');
    await submit(fixture);

    expect(invite).toHaveBeenCalledWith('luis@example.test', ['analyst']);
    const link = (fixture.nativeElement as HTMLElement).querySelector<HTMLInputElement>(
      'input[readonly]',
    );
    expect(link?.value).toBe(`${location.origin}/invitacion#secret-token`);
    expect(text(fixture)).toContain('no se volverá a mostrar');
  });

  it('does not call the API with an invalid email', async () => {
    const invite = vi.fn();
    const { fixture } = setup(InviteDialog, { invite });

    await fill(fixture, 'sin-arroba');
    await submit(fixture);

    expect(invite).not.toHaveBeenCalled();
  });

  it('explains that the person is already a member', async () => {
    const { fixture } = setup(InviteDialog, {
      invite: () => Promise.reject(conflict('already_member')),
    });

    await fill(fixture, 'ana@example.test');
    await submit(fixture);

    expect(text(fixture)).toContain('Esa persona ya es miembro de la organización.');
  });
});

describe('RolesDialog', () => {
  it('saves the new roles and closes', async () => {
    const setRoles = vi.fn(() => Promise.resolve());
    const { fixture, close } = setup(RolesDialog, { setRoles });
    await fixture.whenStable();

    const reviewer = (fixture.nativeElement as HTMLElement).querySelectorAll<HTMLInputElement>(
      'input[type="checkbox"]',
    )[2];
    reviewer.click();
    await submit(fixture);

    expect(setRoles).toHaveBeenCalledWith('u1', ['admin', 'reviewer']);
    expect(close).toHaveBeenCalledWith(true);
  });

  it('explains why the last admin keeps the role', async () => {
    const { fixture, close } = setup(RolesDialog, {
      setRoles: () => Promise.reject(conflict('last_admin')),
    });
    await fixture.whenStable();

    await submit(fixture);

    expect(text(fixture)).toContain('al menos una persona con el rol de administración');
    expect(close).not.toHaveBeenCalled();
  });
});

describe('RemovalDialog', () => {
  it('removes the member and closes', async () => {
    const remove = vi.fn(() => Promise.resolve());
    const { fixture, close } = setup(RemovalDialog, { remove });
    await fixture.whenStable();

    const buttons = (fixture.nativeElement as HTMLElement).querySelectorAll('button');
    buttons[buttons.length - 1].click();
    await fixture.whenStable();

    expect(text(fixture)).toContain('¿Dar de baja a Ana Torres?');
    expect(remove).toHaveBeenCalledWith('u1');
    expect(close).toHaveBeenCalledWith(true);
  });
});
