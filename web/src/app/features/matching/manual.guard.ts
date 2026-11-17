import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';

const PERIOD = /^\d{4}-\d{2}-01$/;

export const monthChosenGuard: CanActivateFn = (route) => {
  const cuenta = route.queryParamMap.get('cuenta');
  const mes = route.queryParamMap.get('mes');
  return cuenta && mes && PERIOD.test(mes) ? true : inject(Router).createUrlTree(['/bandeja']);
};
