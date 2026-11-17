import { groupBySection, itemFor, NAVIGATION, NavigationItem, visibleItems } from './navigation';

const ITEMS: NavigationItem[] = [
  {
    path: '/',
    label: 'Inicio',
    icon: 'home',
    section: 'Conciliación',
    roles: ['admin', 'analyst', 'reviewer'],
  },
  {
    path: '/equipo',
    label: 'Equipo',
    icon: 'account_circle',
    section: 'Administración',
    roles: ['admin'],
  },
  {
    path: '/aprobaciones',
    label: 'Aprobaciones',
    icon: 'check',
    section: 'Control',
    roles: ['reviewer'],
  },
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

describe('groupBySection', () => {
  it('keeps the order and starts a group at each change of section', () => {
    const groups = groupBySection(NAVIGATION);

    expect(groups.map((group) => group.section)).toEqual([
      'Conciliación',
      'Control',
      'Administración',
    ]);
    expect(groups[0].items.map((item) => item.label)).toEqual([
      'Inicio',
      'Bandeja',
      'Panel',
      'Importaciones',
      'Cobros',
    ]);
  });

  it('returns no groups for no items', () => {
    expect(groupBySection([])).toEqual([]);
  });
});

describe('itemFor', () => {
  it('finds the item of a page and of the pages below it', () => {
    expect(itemFor('/bandeja', NAVIGATION)?.label).toBe('Bandeja');
    expect(itemFor('/bandeja/manual?cuenta=1', NAVIGATION)?.label).toBe('Bandeja');
    expect(itemFor('/perfiles/nuevo', NAVIGATION)?.label).toBe('Perfiles de importación');
    expect(itemFor('/', NAVIGATION)?.label).toBe('Inicio');
  });

  it('finds nothing for pages outside the navigation', () => {
    expect(itemFor('/sin-permiso', NAVIGATION)).toBeUndefined();
    expect(itemFor('/bandejas', NAVIGATION)).toBeUndefined();
  });
});
