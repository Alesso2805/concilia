import { TestBed } from '@angular/core/testing';
import {
  ActivatedRouteSnapshot,
  Params,
  provideRouter,
  Router,
  RouterStateSnapshot,
  UrlTree,
  convertToParamMap,
} from '@angular/router';

import { monthChosenGuard } from './manual.guard';

function check(queryParams: Params): string | boolean {
  const route = { queryParamMap: convertToParamMap(queryParams) } as ActivatedRouteSnapshot;
  const result = TestBed.runInInjectionContext(() =>
    monthChosenGuard(route, {} as RouterStateSnapshot),
  );
  return result instanceof UrlTree
    ? TestBed.inject(Router).serializeUrl(result)
    : (result as boolean);
}

describe('monthChosenGuard', () => {
  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideRouter([])] });
  });

  it('opens the manual page for a chosen account and month', () => {
    expect(check({ cuenta: 'a1', mes: '2026-11-01' })).toBe(true);
  });

  it('sends a link without the account or the month back to the inbox', () => {
    expect(check({})).toBe('/bandeja');
    expect(check({ cuenta: 'a1' })).toBe('/bandeja');
    expect(check({ mes: '2026-11-01' })).toBe('/bandeja');
  });

  it('sends a malformed month back to the inbox', () => {
    expect(check({ cuenta: 'a1', mes: 'noviembre' })).toBe('/bandeja');
  });
});
