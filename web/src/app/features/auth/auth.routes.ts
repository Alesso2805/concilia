import { Routes } from '@angular/router';

import { signedInGuard } from '../../core/session/guards';
import { LoginPage } from './login.page';
import { OrganizationPage } from './organization.page';

const routes: Routes = [
  { path: '', component: LoginPage, title: 'Iniciar sesión · Concilia' },
  {
    path: 'organizacion',
    canMatch: [signedInGuard],
    component: OrganizationPage,
    title: 'Elegir organización · Concilia',
  },
];

export default routes;
