import {
  provideHttpClient,
  withFetch,
  withInterceptors,
  withXsrfConfiguration,
} from '@angular/common/http';
import { ApplicationConfig, inject, provideBrowserGlobalErrorListeners } from '@angular/core';
import {
  RedirectCommand,
  Router,
  provideRouter,
  withComponentInputBinding,
  withNavigationErrorHandler,
} from '@angular/router';

import { provideApiConfiguration } from './api/api-configuration';
import { ERROR_PATH, routes } from './app.routes';
import { sessionInterceptor } from './core/http/session.interceptor';
import { XSRF_COOKIE, XSRF_HEADER } from './core/http/xsrf';
import { provideIcons } from './core/icons';

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideRouter(
      routes,
      withComponentInputBinding(),
      withNavigationErrorHandler(() => new RedirectCommand(inject(Router).parseUrl(ERROR_PATH))),
    ),
    provideHttpClient(
      withFetch(),
      withXsrfConfiguration({ cookieName: XSRF_COOKIE, headerName: XSRF_HEADER }),
      withInterceptors([sessionInterceptor]),
    ),
    provideApiConfiguration(''),
    provideIcons(),
  ],
};
