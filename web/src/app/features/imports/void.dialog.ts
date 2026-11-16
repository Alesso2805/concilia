import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';

import { ImportsService, importErrorMessage } from './imports.service';

@Component({
  selector: 'app-void-dialog',
  imports: [
    ReactiveFormsModule,
    MatButtonModule,
    MatDialogModule,
    MatFormFieldModule,
    MatInputModule,
  ],
  template: `
    <h2 mat-dialog-title>¿Anular esta importación?</h2>
    <form [formGroup]="form" (ngSubmit)="confirm()" novalidate>
      <mat-dialog-content class="void">
        <p>
          Sus movimientos dejarán de contar y podrás volver a importar el archivo. Queda registrado
          en la auditoría.
        </p>
        <mat-form-field appearance="outline">
          <mat-label>Motivo</mat-label>
          <textarea matInput formControlName="reason" maxlength="500" required></textarea>
          <mat-error>Indica el motivo.</mat-error>
        </mat-form-field>
        @if (error(); as message) {
          <p class="void__error" role="alert">{{ message }}</p>
        }
      </mat-dialog-content>
      <mat-dialog-actions align="end">
        <button mat-button type="button" [mat-dialog-close]="false">Cancelar</button>
        <button mat-flat-button type="submit" [disabled]="running()">Anular importación</button>
      </mat-dialog-actions>
    </form>
  `,
  styles: `
    .void {
      display: grid;
      min-width: min(420px, 80vw);
      gap: 8px;
    }
    .void__error {
      margin: 0;
      color: var(--mat-sys-error);
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class VoidDialog {
  private readonly imports = inject(ImportsService);
  private readonly dialog = inject<MatDialogRef<VoidDialog, boolean>>(MatDialogRef);
  private readonly fileId = inject<string>(MAT_DIALOG_DATA);

  protected readonly form = new FormGroup({
    reason: new FormControl('', {
      nonNullable: true,
      validators: [Validators.required, Validators.maxLength(500)],
    }),
  });
  protected readonly running = signal(false);
  protected readonly error = signal<string | null>(null);

  protected async confirm(): Promise<void> {
    const reason = this.form.controls.reason.value.trim();
    if (!reason) {
      this.form.markAllAsTouched();
      return;
    }
    this.running.set(true);
    this.error.set(null);
    try {
      await this.imports.void(this.fileId, reason);
      this.dialog.close(true);
    } catch (error) {
      this.error.set(importErrorMessage(error));
    } finally {
      this.running.set(false);
    }
  }
}
