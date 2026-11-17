import { IconName } from '../icons';
import { Role } from '../session/roles';

export type NavigationSection = 'Conciliación' | 'Control' | 'Administración';

export interface NavigationItem {
  path: string;
  label: string;
  icon: IconName;
  section: NavigationSection;
  roles: readonly Role[];
}

export interface NavigationGroup {
  section: NavigationSection;
  items: NavigationItem[];
}

const EVERYONE: readonly Role[] = ['admin', 'analyst', 'reviewer'];

export const NAVIGATION: readonly NavigationItem[] = [
  { path: '/', label: 'Inicio', icon: 'home', section: 'Conciliación', roles: EVERYONE },
  { path: '/bandeja', label: 'Bandeja', icon: 'inbox', section: 'Conciliación', roles: EVERYONE },
  { path: '/panel', label: 'Panel', icon: 'bar_chart', section: 'Conciliación', roles: EVERYONE },
  {
    path: '/importaciones',
    label: 'Importaciones',
    icon: 'upload_file',
    section: 'Conciliación',
    roles: ['analyst'],
  },
  {
    path: '/cobros',
    label: 'Cobros',
    icon: 'receipt_long',
    section: 'Conciliación',
    roles: EVERYONE,
  },
  { path: '/auditoria', label: 'Auditoría', icon: 'history', section: 'Control', roles: EVERYONE },
  { path: '/equipo', label: 'Equipo', icon: 'group', section: 'Administración', roles: ['admin'] },
  {
    path: '/cuentas',
    label: 'Cuentas bancarias',
    icon: 'account_balance',
    section: 'Administración',
    roles: ['admin'],
  },
  {
    path: '/perfiles',
    label: 'Perfiles de importación',
    icon: 'description',
    section: 'Administración',
    roles: ['admin'],
  },
  {
    path: '/configuracion',
    label: 'Configuración',
    icon: 'settings',
    section: 'Administración',
    roles: ['admin'],
  },
];

export function visibleItems(
  items: readonly NavigationItem[],
  granted: ReadonlySet<string>,
): NavigationItem[] {
  return items.filter((item) => item.roles.some((role) => granted.has(role)));
}

export function groupBySection(items: readonly NavigationItem[]): NavigationGroup[] {
  const groups: NavigationGroup[] = [];
  for (const item of items) {
    const last = groups.at(-1);
    if (last?.section === item.section) {
      last.items.push(item);
    } else {
      groups.push({ section: item.section, items: [item] });
    }
  }
  return groups;
}

/** The item whose path is the longest prefix of `url`, so `/bandeja/manual` belongs to Bandeja. */
export function itemFor(url: string, items: readonly NavigationItem[]): NavigationItem | undefined {
  const path = url.split(/[?#]/)[0];
  let best: NavigationItem | undefined;
  for (const item of items) {
    const matches =
      item.path === '/' ? path === '/' : path === item.path || path.startsWith(`${item.path}/`);
    if (matches && item.path.length > (best?.path.length ?? -1)) {
      best = item;
    }
  }
  return best;
}
