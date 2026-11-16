import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { ReactiveFormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';

import { MemberView } from '../../api/models/member-view';
import { RolePicker, roleGroup, selectedRoles } from './role-picker';
import { TeamService, teamErrorMessage } from './team.service';

@Component({
  selector: 'app-roles-dialog',
  imports: [ReactiveFormsModule, MatButtonModule, MatDialogModule, RolePicker],
  template: `
    <h2 mat-dialog-title>Roles de {{ member.display_name }}</h2>
    <form [formGroup]="roles" (ngSubmit)="save()" novalidate>
      <mat-dialog-content class="dialog">
        <app-role-picker [group]="roles" />
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
export class RolesDialog {
  private readonly team = inject(TeamService);
  private readonly dialog = inject<MatDialogRef<RolesDialog, boolean>>(MatDialogRef);

  protected readonly member = inject<MemberView>(MAT_DIALOG_DATA);
  protected readonly roles = roleGroup(this.member.roles);
  protected readonly saving = signal(false);
  protected readonly error = signal<string | null>(null);

  protected async save(): Promise<void> {
    if (this.roles.invalid) {
      this.roles.markAllAsTouched();
      return;
    }
    this.saving.set(true);
    this.error.set(null);
    try {
      await this.team.setRoles(this.member.user_id, selectedRoles(this.roles));
      this.dialog.close(true);
    } catch (error) {
      this.error.set(teamErrorMessage(error));
    } finally {
      this.saving.set(false);
    }
  }
}

@Component({
  selector: 'app-removal-dialog',
  imports: [MatButtonModule, MatDialogModule],
  template: `
    <h2 mat-dialog-title>¿Dar de baja a {{ member.display_name }}?</h2>
    <mat-dialog-content class="dialog">
      <p>
        Perderá el acceso a esta organización y se cerrarán sus sesiones. Su historial se conserva.
        Para volver necesitará una nueva invitación.
      </p>
      @if (error(); as message) {
        <p class="dialog__error" role="alert">{{ message }}</p>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button type="button" [mat-dialog-close]="false">Cancelar</button>
      <button mat-flat-button type="button" [disabled]="removing()" (click)="remove()">
        Dar de baja
      </button>
    </mat-dialog-actions>
  `,
  styleUrl: './dialog.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RemovalDialog {
  private readonly team = inject(TeamService);
  private readonly dialog = inject<MatDialogRef<RemovalDialog, boolean>>(MatDialogRef);

  protected readonly member = inject<MemberView>(MAT_DIALOG_DATA);
  protected readonly removing = signal(false);
  protected readonly error = signal<string | null>(null);

  protected async remove(): Promise<void> {
    this.removing.set(true);
    this.error.set(null);
    try {
      await this.team.remove(this.member.user_id);
      this.dialog.close(true);
    } catch (error) {
      this.error.set(teamErrorMessage(error));
    } finally {
      this.removing.set(false);
    }
  }
}
