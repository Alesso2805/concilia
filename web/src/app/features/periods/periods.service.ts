import { inject, Injectable } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { Api } from '../../api/api';
import { decidePeriod } from '../../api/functions';
import { PeriodEventView } from '../../api/models/period-event-view';
import { newId } from '../../core/ids';

export interface AccountMonth {
  accountId: string;
  period: string;
}

@Injectable({ providedIn: 'root' })
export class PeriodsService {
  private readonly api = inject(Api);

  close(month: AccountMonth): Promise<PeriodEventView> {
    return this.decide(month, 'close', null);
  }

  reopen(month: AccountMonth, reason: string): Promise<PeriodEventView> {
    return this.decide(month, 'reopen', reason);
  }

  private decide(
    month: AccountMonth,
    action: 'close' | 'reopen',
    reason: string | null,
  ): Promise<PeriodEventView> {
    return firstValueFrom(
      this.api.invoke(decidePeriod, {
        body: {
          id: newId(),
          bank_account_id: month.accountId,
          period: month.period,
          action,
          reason,
        },
      }),
    );
  }
}
