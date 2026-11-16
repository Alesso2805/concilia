import { IconName } from '../icons';
import { Role } from '../session/roles';

export interface NavigationItem {
  path: string;
  label: string;
  icon: IconName;
  roles: readonly Role[];
}

const EVERYONE: readonly Role[] = ['admin', 'analyst', 'reviewer'];

export const NAVIGATION: readonly NavigationItem[] = [
  { path: '/', label: 'Inicio', icon: 'home', roles: EVERYONE },
];

export function visibleItems(
  items: readonly NavigationItem[],
  granted: ReadonlySet<string>,
): NavigationItem[] {
  return items.filter((item) => item.roles.some((role) => granted.has(role)));
}
