export type Role = 'admin' | 'analyst' | 'reviewer';

export const ROLE_LABELS: Record<Role, string> = {
  admin: 'Administración',
  analyst: 'Análisis',
  reviewer: 'Revisión',
};

export function roleLabel(role: string): string {
  return ROLE_LABELS[role as Role] ?? role;
}
