import { HttpErrorResponse } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { Api } from '../../api/api';
import { getDashboard, listInboxPeriods } from '../../api/functions';
import { DashboardView } from '../../api/models/dashboard-view';
import { PeriodView } from '../../api/models/period-view';

export interface AccountMonth {
  accountId: string;
  period: string;
}

const MESSAGES: Record<string, string> = {
  not_found: 'No encontramos esa cuenta. Actualiza la página.',
  invalid_period: 'Elige un mes válido.',
  role_required: 'Tu rol no permite ver el panel.',
};

export function reportsErrorMessage(error: unknown): string {
  const code = error instanceof HttpErrorResponse ? (error.error?.detail as string) : null;
  return (code && MESSAGES[code]) || 'No pudimos cargar el panel. Intenta de nuevo.';
}

@Injectable({ providedIn: 'root' })
export class ReportsService {
  private readonly api = inject(Api);

  periods(accountId: string): Promise<PeriodView[]> {
    return firstValueFrom(this.api.invoke(listInboxPeriods, { bank_account_id: accountId }));
  }

  dashboard(month: AccountMonth): Promise<DashboardView> {
    return firstValueFrom(
      this.api.invoke(getDashboard, { bank_account_id: month.accountId, period: month.period }),
    );
  }
}
