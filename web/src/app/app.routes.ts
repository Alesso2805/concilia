import { Routes } from '@angular/router';

import { ErrorPage, ForbiddenPage, NotFoundPage } from './core/pages/status-pages';
import { organizationGuard, roleGuard } from './core/session/guards';

export const ERROR_PATH = '/error';

const adminOnly = roleGuard('admin');

export const routes: Routes = [
  { path: 'iniciar-sesion', loadChildren: () => import('./features/auth/auth.routes') },
  { path: 'error', component: ErrorPage, title: 'Error · Concilia' },
  {
    path: 'invitacion',
    loadComponent: () => import('./features/auth/invitation.page').then((m) => m.InvitationPage),
    title: 'Invitación · Concilia',
  },
  {
    path: '',
    canMatch: [organizationGuard],
    loadComponent: () => import('./core/layout/shell.component').then((m) => m.ShellComponent),
    children: [
      { path: '', loadChildren: () => import('./features/home/home.routes') },
      {
        path: 'equipo',
        canMatch: [adminOnly],
        loadComponent: () => import('./features/admin/team.page').then((m) => m.TeamPage),
        title: 'Equipo · Concilia',
      },
      {
        path: 'cuentas',
        canMatch: [adminOnly],
        loadComponent: () => import('./features/admin/accounts.page').then((m) => m.AccountsPage),
        title: 'Cuentas bancarias · Concilia',
      },
      {
        path: 'perfiles',
        canMatch: [adminOnly],
        loadComponent: () => import('./features/admin/profiles.page').then((m) => m.ProfilesPage),
        title: 'Perfiles de importación · Concilia',
      },
      {
        path: 'perfiles/nuevo',
        canMatch: [adminOnly],
        loadComponent: () =>
          import('./features/admin/profile-editor.page').then((m) => m.ProfileEditorPage),
        title: 'Nuevo perfil · Concilia',
      },
      {
        path: 'perfiles/:id',
        canMatch: [adminOnly],
        loadComponent: () =>
          import('./features/admin/profile-editor.page').then((m) => m.ProfileEditorPage),
        title: 'Editar perfil · Concilia',
      },
      {
        path: 'configuracion',
        canMatch: [adminOnly],
        loadComponent: () => import('./features/admin/settings.page').then((m) => m.SettingsPage),
        title: 'Configuración · Concilia',
      },
      { path: 'sin-permiso', component: ForbiddenPage, title: 'Sin acceso · Concilia' },
      { path: '**', component: NotFoundPage, title: 'Página no encontrada · Concilia' },
    ],
  },
];
