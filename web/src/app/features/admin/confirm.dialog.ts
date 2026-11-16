import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';

import { bankingErrorMessage } from './banking.service';

export interface ConfirmData {
  title: string;
  message: string;
  action: string;
  run: () => Promise<void>;
}

@Component({
  selector: 'app-confirm-dialog',
  imports: [MatButtonModule, MatDialogModule],
  template: `
    <h2 mat-dialog-title>{{ data.title }}</h2>
    <mat-dialog-content class="dialog">
      <p>{{ data.message }}</p>
      @if (error(); as message) {
        <p class="dialog__error" role="alert">{{ message }}</p>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button type="button" [mat-dialog-close]="false">Cancelar</button>
      <button mat-flat-button type="button" [disabled]="running()" (click)="confirm()">
        {{ data.action }}
      </button>
    </mat-dialog-actions>
  `,
  styleUrl: './dialog.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ConfirmDialog {
  private readonly dialog = inject<MatDialogRef<ConfirmDialog, boolean>>(MatDialogRef);

  protected readonly data = inject<ConfirmData>(MAT_DIALOG_DATA);
  protected readonly running = signal(false);
  protected readonly error = signal<string | null>(null);

  protected async confirm(): Promise<void> {
    this.running.set(true);
    this.error.set(null);
    try {
      await this.data.run();
      this.dialog.close(true);
    } catch (error) {
      this.error.set(bankingErrorMessage(error));
    } finally {
      this.running.set(false);
    }
  }
}
