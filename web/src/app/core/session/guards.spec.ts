import { TestBed } from '@angular/core/testing';
import {
  CanMatchFn,
  PartialMatchRouteSnapshot,
  Router,
  UrlSegment,
  UrlTree,
  provideRouter,
} from '@angular/router';

import { SessionView } from '../../api/models/session-view';
import { organizationGuard, roleGuard, signedInGuard } from './guards';
import { Role } from './roles';
import { SessionStore } from './session.store';

function withSession(session: SessionView | null): void {
  const roles = new Set(session?.roles ?? []);
  TestBed.configureTestingModule({
    providers: [
      provideRouter([]),
      {
        provide: SessionStore,
        useValue: {
          restore: () => Promise.resolve(session),
          hasAnyRole: (wanted: Role[]) => wanted.some((role) => roles.has(role)),
        },
      },
    ],
  });
}

function session(organizationId: string | null, roles: Role[] = ['analyst']): SessionView {
  return { user_id: 'u', organization_id: organizationId, organizations: [], roles };
}

const segments = [new UrlSegment('conciliacion', {}), new UrlSegment('bandeja', {})];

async function check(guard: CanMatchFn): Promise<string | boolean> {
  const snapshot = {} as PartialMatchRouteSnapshot;
  const result = await TestBed.runInInjectionContext(() => guard({}, segments, snapshot));
  return result instanceof UrlTree
    ? TestBed.inject(Router).serializeUrl(result)
    : (result as boolean);
}

describe('organizationGuard', () => {
  it('sends a visitor to the login with the way back', async () => {
    withSession(null);

    expect(await check(organizationGuard)).toBe('/iniciar-sesion?volver=%2Fconciliacion%2Fbandeja');
  });

  it('asks for an organization when the session has none', async () => {
    withSession(session(null));

    expect(await check(organizationGuard)).toBe(
      '/iniciar-sesion/organizacion?volver=%2Fconciliacion%2Fbandeja',
    );
  });

  it('lets a member with an organization in', async () => {
    withSession(session('org-1'));

    expect(await check(organizationGuard)).toBe(true);
  });
});

describe('signedInGuard', () => {
  it('needs a session', async () => {
    withSession(null);

    expect(await check(signedInGuard)).toBe('/iniciar-sesion');
  });
});

describe('roleGuard', () => {
  it('lets in any of the allowed roles', async () => {
    withSession(session('org-1', ['reviewer']));

    expect(await check(roleGuard('analyst', 'reviewer'))).toBe(true);
  });

  it('sends everyone else to the forbidden page', async () => {
    withSession(session('org-1', ['analyst']));

    expect(await check(roleGuard('admin'))).toBe('/sin-permiso');
  });
});
