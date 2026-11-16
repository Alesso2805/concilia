import { HttpErrorResponse } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { Api } from '../../api/api';
import {
  archiveBankAccount,
  archiveImportProfile,
  createBankAccount,
  createImportProfile,
  getOrganizationSettings,
  listBankAccounts,
  listImportProfiles,
  listImportTemplates,
  updateBankAccount,
  updateImportProfile,
  updateOrganizationSettings,
} from '../../api/functions';
import { AccountRequest } from '../../api/models/account-request';
import { BankAccountView } from '../../api/models/bank-account-view';
import { OrganizationSettingsRequest } from '../../api/models/organization-settings-request';
import { OrganizationSettingsView } from '../../api/models/organization-settings-view';
import { ReceivablesConfig } from '../../api/models/receivables-config';
import { ReceivablesProfileView } from '../../api/models/receivables-profile-view';
import { ReceivablesTemplateView } from '../../api/models/receivables-template-view';
import { StatementConfig } from '../../api/models/statement-config';
import { StatementProfileView } from '../../api/models/statement-profile-view';
import { StatementTemplateView } from '../../api/models/statement-template-view';
import { newId } from '../../core/ids';

export type ProfileView = StatementProfileView | ReceivablesProfileView;
export type TemplateView = StatementTemplateView | ReceivablesTemplateView;

export type ProfileDraft =
  | { kind: 'bank_statement'; name: string; bank_account_id: string; config: StatementConfig }
  | { kind: 'receivables'; name: string; config: ReceivablesConfig };

const MESSAGES: Record<string, string> = {
  archived: 'Está archivado y ya no se puede cambiar.',
  invalid_last4: 'Ingresa exactamente los últimos 4 dígitos.',
  invalid_settings: 'Revisa los valores: hay tasas repetidas o fuera de rango.',
  kind_mismatch: 'El tipo del perfil no coincide con su configuración.',
  not_found: 'Ya no existe. Actualiza la página.',
};

export function bankingErrorMessage(error: unknown): string {
  if (
    error instanceof HttpErrorResponse &&
    error.status === 422 &&
    Array.isArray(error.error?.detail)
  ) {
    return 'Revisa los campos marcados: la configuración no es válida.';
  }
  const detail = error instanceof HttpErrorResponse ? (error.error?.detail as string) : '';
  return MESSAGES[detail] ?? 'No pudimos completar la operación. Intenta de nuevo.';
}

@Injectable({ providedIn: 'root' })
export class BankingService {
  private readonly api = inject(Api);

  accounts(): Promise<BankAccountView[]> {
    return firstValueFrom(this.api.invoke(listBankAccounts));
  }

  createAccount(account: AccountRequest): Promise<BankAccountView> {
    return firstValueFrom(
      this.api.invoke(createBankAccount, { body: { id: newId(), ...account } }),
    );
  }

  updateAccount(accountId: string, account: AccountRequest): Promise<void> {
    return firstValueFrom(
      this.api.invoke(updateBankAccount, { account_id: accountId, body: account }),
    );
  }

  archiveAccount(accountId: string): Promise<void> {
    return firstValueFrom(this.api.invoke(archiveBankAccount, { account_id: accountId }));
  }

  templates(): Promise<TemplateView[]> {
    return firstValueFrom(this.api.invoke(listImportTemplates));
  }

  profiles(): Promise<ProfileView[]> {
    return firstValueFrom(this.api.invoke(listImportProfiles));
  }

  createProfile(draft: ProfileDraft): Promise<ProfileView> {
    return firstValueFrom(
      this.api.invoke(createImportProfile, { body: { id: newId(), ...draft } }),
    );
  }

  updateProfile(profileId: string, draft: ProfileDraft): Promise<void> {
    const body =
      draft.kind === 'bank_statement'
        ? { kind: draft.kind, name: draft.name, config: draft.config }
        : draft;
    return firstValueFrom(this.api.invoke(updateImportProfile, { profile_id: profileId, body }));
  }

  archiveProfile(profileId: string): Promise<void> {
    return firstValueFrom(this.api.invoke(archiveImportProfile, { profile_id: profileId }));
  }

  settings(): Promise<OrganizationSettingsView> {
    return firstValueFrom(this.api.invoke(getOrganizationSettings));
  }

  updateSettings(settings: OrganizationSettingsRequest): Promise<void> {
    return firstValueFrom(this.api.invoke(updateOrganizationSettings, { body: settings }));
  }
}
