import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import {
  AbstractControl,
  FormControl,
  FormGroup,
  ReactiveFormsModule,
  ValidationErrors,
} from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';

function notBlank(control: AbstractControl<string>): ValidationErrors | null {
  return control.value.trim() ? null : { required: true };
}

@Component({
  selector: 'app-reopen-period-dialog',
  imports: [
    ReactiveFormsModule,
    MatButtonModule,
    MatDialogModule,
    MatFormFieldModule,
    MatInputModule,
  ],
  template: `
    <h2 mat-dialog-title>Reabrir {{ monthName }}</h2>
    <form [formGroup]="form" (ngSubmit)="submit()">
      <mat-dialog-content>
        <p>
          Al reabrirlo se podrán volver a decidir coincidencias, correr el motor e importar
          movimientos de este mes. Queda en la auditoría con el motivo.
        </p>
        <mat-form-field appearance="outline" class="reopen__reason">
          <mat-label>Motivo</mat-label>
          <textarea matInput formControlName="reason" maxlength="500" required></textarea>
          @if (form.controls.reason.invalid && form.controls.reason.touched) {
            <mat-error>Indica el motivo.</mat-error>
          }
        </mat-form-field>
      </mat-dialog-content>
      <mat-dialog-actions align="end">
        <button mat-button type="button" mat-dialog-close>Cancelar</button>
        <button mat-flat-button type="submit">Reabrir</button>
      </mat-dialog-actions>
    </form>
  `,
  styles: '.reopen__reason { width: 100%; }',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ReopenPeriodDialog {
  private readonly dialog = inject<MatDialogRef<ReopenPeriodDialog, string>>(MatDialogRef);
  protected readonly monthName = inject<string>(MAT_DIALOG_DATA);
  protected readonly form = new FormGroup({
    reason: new FormControl('', { nonNullable: true, validators: [notBlank] }),
  });

  protected submit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    this.dialog.close(this.form.controls.reason.value.trim());
  }
}
