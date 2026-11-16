import { inject } from '@angular/core';
import { CanMatchFn, Router } from '@angular/router';

import { FORBIDDEN_PATH, LOGIN_PATH, ORGANIZATION_PICKER_PATH } from './paths';
import { Role } from './roles';
import { SessionStore } from './session.store';

export const organizationGuard: CanMatchFn = async (_route, segments) => {
  const router = inject(Router);
  const session = await inject(SessionStore).restore();
  const volver = '/' + segments.map((segment) => segment.path).join('/');
  if (!session) {
    return router.createUrlTree([LOGIN_PATH], { queryParams: { volver } });
  }
  return session.organization_id
    ? true
    : router.createUrlTree([ORGANIZATION_PICKER_PATH], { queryParams: { volver } });
};

export const signedInGuard: CanMatchFn = async () => {
  const router = inject(Router);
  const session = await inject(SessionStore).restore();
  return session ? true : router.createUrlTree([LOGIN_PATH]);
};

export function roleGuard(...allowed: Role[]): CanMatchFn {
  return async () => {
    const router = inject(Router);
    const store = inject(SessionStore);
    await store.restore();
    return store.hasAnyRole(allowed) ? true : router.createUrlTree([FORBIDDEN_PATH]);
  };
}
