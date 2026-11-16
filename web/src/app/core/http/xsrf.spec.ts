import { HttpClient, HttpXsrfTokenExtractor } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { firstValueFrom } from 'rxjs';

import { appConfig } from '../../app.config';
import { XSRF_HEADER } from './xsrf';

describe('XSRF configuration', () => {
  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        ...appConfig.providers,
        provideHttpClientTesting(),
        { provide: HttpXsrfTokenExtractor, useValue: { getToken: () => 'signed-token' } },
      ],
    });
  });

  afterEach(() => TestBed.inject(HttpTestingController).verify());

  it('sends the token header on API writes', async () => {
    const http = TestBed.inject(HttpClient);

    const done = firstValueFrom(http.post('/api/app/logout', null));
    const request = TestBed.inject(HttpTestingController).expectOne('/api/app/logout');
    request.flush(null);
    await done;

    expect(request.request.headers.get(XSRF_HEADER)).toBe('signed-token');
  });

  it('does not send it on reads', async () => {
    const http = TestBed.inject(HttpClient);

    const done = firstValueFrom(http.get('/api/app/session'));
    const request = TestBed.inject(HttpTestingController).expectOne('/api/app/session');
    request.flush({});
    await done;

    expect(request.request.headers.has(XSRF_HEADER)).toBe(false);
  });
});
