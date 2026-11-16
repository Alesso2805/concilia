import { HttpErrorResponse } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { Api } from '../../api/api';
import { acceptInvitation, acceptInvitationWithNewAccount } from '../../api/functions';

export interface NewAccount {
  email: string;
  display_name: string;
  password: string;
}

export function invitationErrorMessage(error: unknown): string {
  const detail = error instanceof HttpErrorResponse ? (error.error?.detail as unknown) : null;
  if (detail === 'password_too_short') {
    return 'La contraseña debe tener al menos 12 caracteres.';
  }
  if (detail === 'invitation_not_valid') {
    return (
      'No pudimos aceptar la invitación. Puede haber vencido, haber sido revocada o ser para ' +
      'otro correo. Si ya tienes una cuenta, inicia sesión para aceptarla.'
    );
  }
  return 'No pudimos conectar con el servidor. Intenta de nuevo.';
}

@Injectable({ providedIn: 'root' })
export class InvitationService {
  private readonly api = inject(Api);

  async acceptAsMember(token: string): Promise<string> {
    const accepted = await firstValueFrom(this.api.invoke(acceptInvitation, { body: { token } }));
    return accepted.organization_id;
  }

  async acceptWithNewAccount(token: string, account: NewAccount): Promise<void> {
    await firstValueFrom(
      this.api.invoke(acceptInvitationWithNewAccount, { body: { token, ...account } }),
    );
  }
}
