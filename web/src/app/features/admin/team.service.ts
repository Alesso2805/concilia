import { HttpErrorResponse } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { Api } from '../../api/api';
import {
  createInvitation,
  getTeam,
  removeMember,
  revokeInvitation,
  setMemberRoles,
} from '../../api/functions';
import { CreatedInvitationView } from '../../api/models/created-invitation-view';
import { RoleName } from '../../api/models/role-name';
import { TeamView } from '../../api/models/team-view';
import { newId } from '../../core/ids';

const MESSAGES: Record<string, string> = {
  already_member: 'Esa persona ya es miembro de la organización.',
  last_admin: 'La organización necesita al menos una persona con el rol de administración.',
  invalid_email: 'Revisa el formato del correo.',
  invitation_accepted: 'Esa invitación ya fue aceptada.',
  not_found: 'Ya no existe. Actualiza la página.',
};

export function teamErrorMessage(error: unknown): string {
  const detail = error instanceof HttpErrorResponse ? (error.error?.detail as string) : '';
  return MESSAGES[detail] ?? 'No pudimos completar la operación. Intenta de nuevo.';
}

@Injectable({ providedIn: 'root' })
export class TeamService {
  private readonly api = inject(Api);

  load(): Promise<TeamView> {
    return firstValueFrom(this.api.invoke(getTeam));
  }

  invite(email: string, roles: RoleName[]): Promise<CreatedInvitationView> {
    return firstValueFrom(
      this.api.invoke(createInvitation, { body: { id: newId(), email, roles } }),
    );
  }

  revoke(invitationId: string): Promise<void> {
    return firstValueFrom(this.api.invoke(revokeInvitation, { invitation_id: invitationId }));
  }

  setRoles(userId: string, roles: RoleName[]): Promise<void> {
    return firstValueFrom(this.api.invoke(setMemberRoles, { user_id: userId, body: { roles } }));
  }

  remove(userId: string): Promise<void> {
    return firstValueFrom(this.api.invoke(removeMember, { user_id: userId }));
  }
}
