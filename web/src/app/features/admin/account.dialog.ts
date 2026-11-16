import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';

import { BankAccountView } from '../../api/models/bank-account-view';
import { BankingService, bankingErrorMessage } from './banking.service';

export const BANKS = ['BCP', 'Interbank', 'BBVA', 'Scotiabank', 'BanBif', 'Banco de la Nación'];

@Component({
  selector: 'app-account-dialog',
  imports: [
    ReactiveFormsModule,
    MatButtonModule,
    MatDialogModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
  ],
  template: `
    <h2 mat-dialog-title>{{ account ? 'Editar cuenta' : 'Nueva cuenta bancaria' }}</h2>
    <form [formGroup]="form" (ngSubmit)="save()" novalidate>
      <mat-dialog-content class="dialog">
        <mat-form-field appearance="outline">
          <mat-label>Banco</mat-label>
          <mat-select formControlName="bank" required>
            @for (bank of banks; track bank) {
              <mat-option [value]="bank">{{ bank }}</mat-option>
            }
          </mat-select>
          <mat-error>Elige el banco.</mat-error>
        </mat-form-field>
        <mat-form-field appearance="outline">
          <mat-label>Alias</mat-label>
          <input matInput formControlName="alias" maxlength="80" required />
          <mat-hint>Por ejemplo, «Recaudación soles».</mat-hint>
          <mat-error>Ingresa un alias.</mat-error>
        </mat-form-field>
        <mat-form-field appearance="outline">
          <mat-label>Últimos 4 dígitos</mat-label>
          <input
            matInput
            formControlName="number_last4"
            inputmode="numeric"
            maxlength="4"
            required
          />
          <mat-hint>Moneda: soles (PEN).</mat-hint>
          <mat-error>Ingresa exactamente 4 dígitos.</mat-error>
        </mat-form-field>
        @if (error(); as message) {
          <p class="dialog__error" role="alert">{{ message }}</p>
        }
      </mat-dialog-content>
      <mat-dialog-actions align="end">
        <button mat-button type="button" [mat-dialog-close]="false">Cancelar</button>
        <button mat-flat-button type="submit" [disabled]="saving()">Guardar</button>
      </mat-dialog-actions>
    </form>
  `,
  styleUrl: './dialog.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AccountDialog {
  private readonly banking = inject(BankingService);
  private readonly dialog = inject<MatDialogRef<AccountDialog, boolean>>(MatDialogRef);

  protected readonly account = inject<BankAccountView | null>(MAT_DIALOG_DATA);
  protected readonly banks =
    this.account && !BANKS.includes(this.account.bank) ? [...BANKS, this.account.bank] : BANKS;
  protected readonly form = inject(NonNullableFormBuilder).group({
    bank: [this.account?.bank ?? '', Validators.required],
    alias: [this.account?.alias ?? '', [Validators.required, Validators.maxLength(80)]],
    number_last4: [
      this.account?.number_last4 ?? '',
      [Validators.required, Validators.pattern(/^\d{4}$/)],
    ],
  });
  protected readonly saving = signal(false);
  protected readonly error = signal<string | null>(null);

  protected async save(): Promise<void> {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    this.saving.set(true);
    this.error.set(null);
    try {
      const value = this.form.getRawValue();
      if (this.account) {
        await this.banking.updateAccount(this.account.id, value);
      } else {
        await this.banking.createAccount(value);
      }
      this.dialog.close(true);
    } catch (error) {
      this.error.set(bankingErrorMessage(error));
    } finally {
      this.saving.set(false);
    }
  }
}
