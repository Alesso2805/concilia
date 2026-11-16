import { HttpErrorResponse, HttpInterceptorFn, HttpStatusCode } from '@angular/common/http';
import { inject } from '@angular/core';
import { MatSnackBar } from '@angular/material/snack-bar';
import { Router } from '@angular/router';
import { catchError, throwError } from 'rxjs';

import { LOGIN_PATH } from '../session/paths';
import { SessionStore } from '../session/session.store';
import { REDIRECT_ON_401 } from './context';

export const sessionInterceptor: HttpInterceptorFn = (request, next) => {
  const router = inject(Router);
  const store = inject(SessionStore);
  const snackBar = inject(MatSnackBar);
  return next(request).pipe(
    catchError((error: unknown) => {
      if (error instanceof HttpErrorResponse && request.url.startsWith('/api/app/')) {
        if (error.status === HttpStatusCode.Unauthorized && request.context.get(REDIRECT_ON_401)) {
          store.forget();
          const volver = router.url.startsWith(LOGIN_PATH) ? undefined : router.url;
          void router.navigate([LOGIN_PATH], { queryParams: { volver } });
        } else if (error.status === HttpStatusCode.Forbidden) {
          snackBar.open('No tienes permiso para hacer esto.', 'Cerrar', { duration: 6000 });
        }
      }
      return throwError(() => error);
    }),
  );
};
