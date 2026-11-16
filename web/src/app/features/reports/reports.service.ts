import { HttpErrorResponse } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { Api } from '../../api/api';
import { getDashboard, listInboxPeriods, requestExport } from '../../api/functions';
import { DashboardView } from '../../api/models/dashboard-view';
import { ExportView } from '../../api/models/export-view';
import { PeriodView } from '../../api/models/period-view';
import { newId } from '../../core/ids';

export interface AccountMonth {
  accountId: string;
  period: string;
}

const MESSAGES: Record<string, string> = {
  not_found: 'No encontramos esa cuenta. Actualiza la página.',
  invalid_period: 'Elige un mes válido.',
  role_required: 'Tu rol no permite esta acción.',
  not_ready: 'El Excel todavía se está preparando.',
  expired: 'El Excel venció. Vuelve a exportarlo.',
};

export function reportsErrorMessage(
  error: unknown,
  fallback = 'No pudimos cargar el panel. Intenta de nuevo.',
): string {
  const code = error instanceof HttpErrorResponse ? (error.error?.detail as string) : null;
  return (code && MESSAGES[code]) || fallback;
}

@Injectable({ providedIn: 'root' })
export class ReportsService {
  private readonly api = inject(Api);

  periods(accountId: string): Promise<PeriodView[]> {
    return firstValueFrom(this.api.invoke(listInboxPeriods, { bank_account_id: accountId }));
  }

  requestExport(month: AccountMonth): Promise<ExportView> {
    return firstValueFrom(
      this.api.invoke(requestExport, {
        body: { id: newId(), bank_account_id: month.accountId, period: month.period },
      }),
    );
  }

  exportFileUrl(exportId: string): string {
    return `/api/app/exports/${exportId}/file`;
  }

  dashboard(month: AccountMonth): Promise<DashboardView> {
    return firstValueFrom(
      this.api.invoke(getDashboard, { bank_account_id: month.accountId, period: month.period }),
    );
  }
}
