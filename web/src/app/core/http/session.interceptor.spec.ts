import { HttpClient, HttpContext, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { MatSnackBar } from '@angular/material/snack-bar';
import { Router, provideRouter } from '@angular/router';
import { firstValueFrom } from 'rxjs';

import { SessionStore } from '../session/session.store';
import { REDIRECT_ON_401 } from './context';
import { sessionInterceptor } from './session.interceptor';

describe('sessionInterceptor', () => {
  const forget = vi.fn();
  const open = vi.fn();
  let navigate: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    forget.mockReset();
    open.mockReset();
    TestBed.configureTestingModule({
      providers: [
        provideRouter([]),
        provideHttpClient(withInterceptors([sessionInterceptor])),
        provideHttpClientTesting(),
        { provide: SessionStore, useValue: { forget } },
        { provide: MatSnackBar, useValue: { open } },
      ],
    });
    navigate = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
  });

  async function fail(url: string, status: number, context?: HttpContext): Promise<void> {
    const response = firstValueFrom(TestBed.inject(HttpClient).get(url, { context }));
    TestBed.inject(HttpTestingController).expectOne(url).flush(null, { status, statusText: '' });
    await expect(response).rejects.toMatchObject({ status });
  }

  it('sends an expired session to the login', async () => {
    await fail('/api/app/matches', 401);

    expect(forget).toHaveBeenCalled();
    expect(navigate).toHaveBeenCalledWith(['/iniciar-sesion'], { queryParams: { volver: '/' } });
  });

  it('leaves alone requests that handle their own 401', async () => {
    await fail('/api/app/session', 401, new HttpContext().set(REDIRECT_ON_401, false));
    await fail('/api/public/login', 401);

    expect(navigate).not.toHaveBeenCalled();
    expect(forget).not.toHaveBeenCalled();
  });

  it('warns about a 403', async () => {
    await fail('/api/app/periods/close', 403);

    expect(open).toHaveBeenCalledWith('No tienes permiso para hacer esto.', 'Cerrar', {
      duration: 6000,
    });
    expect(navigate).not.toHaveBeenCalled();
  });
});
