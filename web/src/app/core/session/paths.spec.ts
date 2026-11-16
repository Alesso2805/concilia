import { safeReturnUrl } from './paths';

describe('safeReturnUrl', () => {
  it.each([
    ['/conciliacion?pestana=2', '/conciliacion?pestana=2'],
    [undefined, '/'],
    ['', '/'],
    ['https://example.com', '/'],
    ['//example.com', '/'],
    ['/iniciar-sesion', '/'],
    ['conciliacion', '/'],
  ])('%s → %s', (value, expected) => {
    expect(safeReturnUrl(value)).toBe(expected);
  });
});
