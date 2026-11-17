import { expect, expectAccessible, openApp, SIGNED_IN, test } from './fixtures';

test.use({ storageState: SIGNED_IN });

const SCREENS = [
  { path: '/', heading: /./ },
  { path: '/bandeja', heading: 'Bandeja de conciliación' },
  { path: '/panel', heading: 'Panel' },
  { path: '/importaciones', heading: 'Importaciones' },
  { path: '/cobros', heading: 'Cobros esperados' },
  { path: '/auditoria', heading: 'Auditoría' },
  { path: '/equipo', heading: /Equipo/ },
  { path: '/cuentas', heading: /Cuentas bancarias/ },
  { path: '/perfiles', heading: /Perfiles de importación/ },
  { path: '/perfiles/nuevo', heading: /perfil/i },
  { path: '/configuracion', heading: /Configuración/ },
];

for (const scheme of ['light', 'dark'] as const) {
  for (const screen of SCREENS) {
    test(`${screen.path} has no serious accessibility violations in ${scheme}`, async ({
      page,
    }) => {
      await page.emulateMedia({ colorScheme: scheme });
      await openApp(page, screen.path);
      await expect(page.getByRole('heading', { level: 1, name: screen.heading })).toBeVisible();
      await expectAccessible(page);
    });
  }
}
