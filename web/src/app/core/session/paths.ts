export const LOGIN_PATH = '/iniciar-sesion';
export const ORGANIZATION_PICKER_PATH = '/iniciar-sesion/organizacion';
export const FORBIDDEN_PATH = '/sin-permiso';

export function safeReturnUrl(value: string | null | undefined): string {
  return value?.startsWith('/') && !value.startsWith('//') && !value.startsWith(LOGIN_PATH)
    ? value
    : '/';
}
