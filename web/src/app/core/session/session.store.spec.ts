import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { SessionView } from '../../api/models/session-view';
import { REDIRECT_ON_401 } from '../http/context';
import { SessionStore } from './session.store';

const ORGANIZATION = { id: 'org-1', name: 'Comercial Andina', is_demo: false, roles: ['analyst'] };
const SESSION: SessionView = {
  user_id: 'user-1',
  organization_id: 'org-1',
  organizations: [ORGANIZATION],
  roles: ['analyst'],
};

describe('SessionStore', () => {
  let store: SessionStore;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    store = TestBed.inject(SessionStore);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('restores the session once and exposes its organization and roles', async () => {
    const first = store.restore();
    const second = store.restore();
    http.expectOne('/api/app/session').flush(SESSION);

    expect(await first).toEqual(SESSION);
    expect(await second).toEqual(SESSION);
    expect(store.organization()).toEqual(ORGANIZATION);
    expect(store.hasAnyRole(['reviewer', 'analyst'])).toBe(true);
    expect(store.hasAnyRole(['admin'])).toBe(false);
  });

  it('treats a 401 as signed out without redirecting', async () => {
    const restored = store.restore();
    const request = http.expectOne('/api/app/session');
    request.flush(null, { status: 401, statusText: 'Unauthorized' });

    expect(await restored).toBeNull();
    expect(request.request.context.get(REDIRECT_ON_401)).toBe(false);
  });

  it('tries again after a server error', async () => {
    const failed = store.restore();
    http.expectOne('/api/app/session').flush(null, { status: 503, statusText: 'Unavailable' });
    await expect(failed).rejects.toBeTruthy();

    const retried = store.restore();
    http.expectOne('/api/app/session').flush(SESSION);
    expect(await retried).toEqual(SESSION);
  });

  it('logs in and then reads the new session', async () => {
    const loggedIn = store.login('ana@example.com', 'secret');
    const login = http.expectOne('/api/public/login');
    expect(login.request.body).toEqual({ email: 'ana@example.com', password: 'secret' });
    login.flush({ organization_id: 'org-1', organizations: [ORGANIZATION] });
    await Promise.resolve();
    http.expectOne('/api/app/session').flush(SESSION);

    expect((await loggedIn).organization_id).toBe('org-1');
    expect(store.session()).toEqual(SESSION);
  });

  it('chooses an organization and then reads the new session', async () => {
    const chosen = store.chooseOrganization('org-1');
    const choose = http.expectOne('/api/app/session/organization');
    expect(choose.request.body).toEqual({ organization_id: 'org-1' });
    choose.flush(null);
    await Promise.resolve();
    http.expectOne('/api/app/session').flush(SESSION);
    await chosen;

    expect(store.organization()?.name).toBe('Comercial Andina');
  });

  it('forgets the session even if logout fails', async () => {
    const restored = store.restore();
    http.expectOne('/api/app/session').flush(SESSION);
    await restored;

    const loggedOut = store.logout();
    http.expectOne('/api/app/logout').flush(null, { status: 500, statusText: 'Error' });
    await expect(loggedOut).rejects.toBeTruthy();

    expect(store.session()).toBeNull();
    expect(await store.restore()).toBeNull();
  });
});
