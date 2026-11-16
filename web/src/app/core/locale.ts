import { registerLocaleData } from '@angular/common';
import localeEsPe from '@angular/common/locales/es-PE';
import { LOCALE_ID, Provider } from '@angular/core';

export function provideLocale(): Provider {
  registerLocaleData(localeEsPe);
  return { provide: LOCALE_ID, useValue: 'es-PE' };
}
