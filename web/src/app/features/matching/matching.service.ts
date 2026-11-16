import { HttpErrorResponse } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { Api } from '../../api/api';
import {
  decideMatch,
  getEngineRun,
  getInboxCounts,
  getMatch,
  listFreeCredits,
  listInboxPeriods,
  listMatches,
  requestEngineRun,
} from '../../api/functions';
import { CountsView } from '../../api/models/counts-view';
import { CreditPageView } from '../../api/models/credit-page-view';
import { DecisionRequestBody } from '../../api/models/decision-request-body';
import { RecordedDecisionView } from '../../api/models/recorded-decision-view';
import { EngineRunView } from '../../api/models/engine-run-view';
import { MatchDetailView } from '../../api/models/match-detail-view';
import { MatchPageView } from '../../api/models/match-page-view';
import { PeriodView } from '../../api/models/period-view';
import { newId } from '../../core/ids';

export type MatchTab = 'proposed' | 'confirmed' | 'approved';
export type InboxTab = 'free' | MatchTab;
export type Rule = 'R1' | 'R2' | 'R3' | 'R4' | 'R5' | 'R6';

export interface Month {
  accountId: string;
  period: string;
}

export interface InboxFilters {
  rule: Rule | null;
  minScore: number | null;
  minAmountCents: number | null;
  maxAmountCents: number | null;
}

export interface Cursor {
  after?: string | null;
  before?: string | null;
}

export const NO_FILTERS: InboxFilters = {
  rule: null,
  minScore: null,
  minAmountCents: null,
  maxAmountCents: null,
};

export type Decision = Omit<DecisionRequestBody, 'id'>;

const MESSAGES: Record<string, string> = {
  closed_period: 'El mes está cerrado: no admite cambios.',
  difference_reason:
    'Elige un motivo de diferencia que corresponda: sobrepago solo si sobra dinero, y «Otro» necesita una nota.',
  four_eyes: 'Otra persona debe decidir: tú creaste o confirmaste esta coincidencia.',
  reason_required: 'Indica el motivo.',
  wrong_state: 'La coincidencia cambió de estado. Actualiza la bandeja.',
  invalid_cursor: 'La página ya no es válida. Vuelve a la primera.',
  invalid_period: 'Elige un mes válido.',
  not_found: 'No encontramos lo que buscas. Actualiza la página.',
  role_required: 'Tu rol no permite esta acción.',
  run_in_progress: 'Ya hay una corrida del motor en curso para este mes.',
};

export function matchingCodeMessage(code: string | null | undefined): string {
  return (code && MESSAGES[code]) || 'No pudimos completar la operación. Intenta de nuevo.';
}

export function matchingErrorMessage(error: unknown): string {
  return matchingCodeMessage(
    error instanceof HttpErrorResponse ? (error.error?.detail as string) : null,
  );
}

@Injectable({ providedIn: 'root' })
export class MatchingService {
  private readonly api = inject(Api);

  periods(accountId: string): Promise<PeriodView[]> {
    return firstValueFrom(this.api.invoke(listInboxPeriods, { bank_account_id: accountId }));
  }

  counts(month: Month): Promise<CountsView> {
    return firstValueFrom(
      this.api.invoke(getInboxCounts, { bank_account_id: month.accountId, period: month.period }),
    );
  }

  credits(month: Month, filters: InboxFilters, cursor: Cursor): Promise<CreditPageView> {
    return firstValueFrom(
      this.api.invoke(listFreeCredits, {
        bank_account_id: month.accountId,
        period: month.period,
        min_amount_cents: filters.minAmountCents,
        max_amount_cents: filters.maxAmountCents,
        limit: 25,
        ...cursor,
      }),
    );
  }

  matches(
    month: Month,
    status: MatchTab,
    filters: InboxFilters,
    cursor: Cursor,
  ): Promise<MatchPageView> {
    return firstValueFrom(
      this.api.invoke(listMatches, {
        bank_account_id: month.accountId,
        period: month.period,
        status,
        rule: filters.rule,
        min_score: filters.minScore,
        min_amount_cents: filters.minAmountCents,
        max_amount_cents: filters.maxAmountCents,
        limit: 25,
        ...cursor,
      }),
    );
  }

  detail(matchId: string): Promise<MatchDetailView> {
    return firstValueFrom(this.api.invoke(getMatch, { match_id: matchId }));
  }

  runEngine(month: Month): Promise<EngineRunView> {
    return firstValueFrom(
      this.api.invoke(requestEngineRun, {
        body: { id: newId(), bank_account_id: month.accountId, period: month.period },
      }),
    );
  }

  decide(matchId: string, decision: Decision): Promise<RecordedDecisionView> {
    return firstValueFrom(
      this.api.invoke(decideMatch, { match_id: matchId, body: { id: newId(), ...decision } }),
    );
  }

  run(runId: string): Promise<EngineRunView> {
    return firstValueFrom(this.api.invoke(getEngineRun, { run_id: runId }));
  }
}
