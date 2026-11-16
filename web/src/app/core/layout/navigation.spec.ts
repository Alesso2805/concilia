import { NavigationItem, visibleItems } from './navigation';

const ITEMS: NavigationItem[] = [
  { path: '/', label: 'Inicio', icon: 'home', roles: ['admin', 'analyst', 'reviewer'] },
  { path: '/equipo', label: 'Equipo', icon: 'account_circle', roles: ['admin'] },
  { path: '/aprobaciones', label: 'Aprobaciones', icon: 'check', roles: ['reviewer'] },
];

describe('visibleItems', () => {
  it('shows only what the roles allow', () => {
    expect(visibleItems(ITEMS, new Set(['analyst'])).map((item) => item.label)).toEqual(['Inicio']);
    expect(visibleItems(ITEMS, new Set(['admin', 'reviewer'])).map((item) => item.label)).toEqual([
      'Inicio',
      'Equipo',
      'Aprobaciones',
    ]);
  });

  it('shows nothing without roles', () => {
    expect(visibleItems(ITEMS, new Set())).toEqual([]);
  });
});
