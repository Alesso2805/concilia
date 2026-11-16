import { Routes } from '@angular/router';

import { organizationGuard } from './core/session/guards';

export const routes: Routes = [
  { path: 'iniciar-sesion', loadChildren: () => import('./features/auth/auth.routes') },
  {
    path: '',
    canMatch: [organizationGuard],
    loadChildren: () => import('./features/home/home.routes'),
  },
  { path: '**', redirectTo: '' },
];
