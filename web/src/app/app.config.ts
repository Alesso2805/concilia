import { provideHttpClient, withFetch, withXsrfConfiguration } from '@angular/common/http';
import { ApplicationConfig, provideBrowserGlobalErrorListeners } from '@angular/core';
import { provideRouter } from '@angular/router';

import { provideApiConfiguration } from './api/api-configuration';
import { routes } from './app.routes';
import { XSRF_COOKIE, XSRF_HEADER } from './core/http/xsrf';

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideRouter(routes),
    provideHttpClient(
      withFetch(),
      withXsrfConfiguration({ cookieName: XSRF_COOKIE, headerName: XSRF_HEADER }),
    ),
    provideApiConfiguration(''),
  ],
};
