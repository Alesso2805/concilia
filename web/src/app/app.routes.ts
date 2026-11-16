import { Routes } from '@angular/router';

import { ErrorPage, ForbiddenPage, NotFoundPage } from './core/pages/status-pages';
import { organizationGuard } from './core/session/guards';

export const ERROR_PATH = '/error';

export const routes: Routes = [
  { path: 'iniciar-sesion', loadChildren: () => import('./features/auth/auth.routes') },
  { path: 'error', component: ErrorPage, title: 'Error · Concilia' },
  {
    path: '',
    canMatch: [organizationGuard],
    loadComponent: () => import('./core/layout/shell.component').then((m) => m.ShellComponent),
    children: [
      { path: '', loadChildren: () => import('./features/home/home.routes') },
      { path: 'sin-permiso', component: ForbiddenPage, title: 'Sin acceso · Concilia' },
      { path: '**', component: NotFoundPage, title: 'Página no encontrada · Concilia' },
    ],
  },
];
