import { HttpErrorResponse } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { Api } from '../../api/api';
import {
  decideSuggestion,
  getAiUsage,
  getSuggestion,
  requestSuggestion,
} from '../../api/functions';
import { SuggestionDecisionView } from '../../api/models/suggestion-decision-view';
import { SuggestionView } from '../../api/models/suggestion-view';
import { UsageView } from '../../api/models/usage-view';
import { newId } from '../../core/ids';

const MESSAGES: Record<string, string> = {
  credit_not_free: 'Este abono ya no está libre o su mes está cerrado. Actualiza la bandeja.',
  ai_unavailable: 'La IA no está disponible para tu organización.',
  ai_daily_limit: 'Tu organización llegó al límite de 50 consultas a la IA por hoy.',
  ai_global_limit: 'La IA llegó a su límite diario. Intenta mañana.',
  no_candidates: 'No hay cobros con saldo disponible para sugerir.',
  ai_timeout: 'La IA tardó demasiado. Intenta de nuevo.',
  ai_rate_limited: 'La IA está muy ocupada. Intenta en unos minutos.',
  ai_budget_exhausted: 'La IA no está disponible por hoy.',
  ai_provider_error: 'La IA no respondió. Intenta de nuevo.',
  already_decided: 'Esta sugerencia ya se decidió.',
  invalid_suggestion: 'Esta respuesta de la IA no es válida.',
  insufficient_balance: 'Algún cobro ya no tiene saldo suficiente. Pide otra sugerencia.',
  reason_required: 'Indica el motivo del rechazo.',
  role_required: 'Tu rol no permite esta acción.',
};

export function aiCodeMessage(code: string | null | undefined): string {
  return (code && MESSAGES[code]) || 'No pudimos completar la consulta a la IA. Intenta de nuevo.';
}

export function aiErrorMessage(error: unknown): string {
  return aiCodeMessage(error instanceof HttpErrorResponse ? (error.error?.detail as string) : null);
}

@Injectable({ providedIn: 'root' })
export class AiService {
  private readonly api = inject(Api);

  /** The organization's usage, or null when the AI is turned off for the whole instance. */
  async usage(): Promise<UsageView | null> {
    try {
      return await firstValueFrom(this.api.invoke(getAiUsage));
    } catch (error) {
      if (error instanceof HttpErrorResponse && error.status === 404) {
        return null;
      }
      throw error;
    }
  }

  ask(creditId: string): Promise<SuggestionView> {
    return firstValueFrom(
      this.api.invoke(requestSuggestion, { body: { id: newId(), bank_movement_id: creditId } }),
    );
  }

  suggestion(id: string): Promise<SuggestionView> {
    return firstValueFrom(this.api.invoke(getSuggestion, { suggestion_id: id }));
  }

  decide(
    suggestionId: string,
    index: number,
    action: 'accept' | 'reject',
    reason: string | null,
  ): Promise<SuggestionDecisionView> {
    return firstValueFrom(
      this.api.invoke(decideSuggestion, {
        suggestion_id: suggestionId,
        body: { id: newId(), index, action, reason },
      }),
    );
  }
}
