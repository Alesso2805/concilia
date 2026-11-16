import { HttpErrorResponse } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { Api } from '../../api/api';
import { listAuditActors, listAuditEvents } from '../../api/functions';
import { AuditAction } from '../../api/models/audit-action';
import { AuditActorView } from '../../api/models/audit-actor-view';
import { AuditEntity } from '../../api/models/audit-entity';
import { AuditPageView } from '../../api/models/audit-page-view';

export const AUDIT_PAGE_SIZE = 25;

export interface AuditFilters {
  actorUserId: string | null;
  action: AuditAction | null;
  entity: AuditEntity | null;
  from: string | null;
  to: string | null;
}

export interface AuditCursor {
  after?: string | null;
  before?: string | null;
}

export const NO_AUDIT_FILTERS: AuditFilters = {
  actorUserId: null,
  action: null,
  entity: null,
  from: null,
  to: null,
};

const MESSAGES: Record<string, string> = {
  invalid_range: 'La fecha «desde» debe ser anterior o igual a la fecha «hasta».',
  invalid_cursor: 'La página ya no es válida. Vuelve a la primera.',
  role_required: 'Tu rol no permite ver la auditoría.',
};

export function auditErrorMessage(error: unknown): string {
  const code = error instanceof HttpErrorResponse ? (error.error?.detail as string) : null;
  return (code && MESSAGES[code]) || 'No pudimos cargar la auditoría. Intenta de nuevo.';
}

@Injectable({ providedIn: 'root' })
export class AuditService {
  private readonly api = inject(Api);

  events(filters: AuditFilters, cursor: AuditCursor): Promise<AuditPageView> {
    return firstValueFrom(
      this.api.invoke(listAuditEvents, {
        actor_user_id: filters.actorUserId,
        action: filters.action,
        entity: filters.entity,
        from: filters.from,
        to: filters.to,
        limit: AUDIT_PAGE_SIZE,
        ...cursor,
      }),
    );
  }

  actors(): Promise<AuditActorView[]> {
    return firstValueFrom(this.api.invoke(listAuditActors));
  }
}
