import { ClipboardModule } from '@angular/cdk/clipboard';
import { DOCUMENT } from '@angular/common';
import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatDialogModule } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';

import { RolePicker, roleGroup, selectedRoles } from './role-picker';
import { TeamService, teamErrorMessage } from './team.service';

@Component({
  selector: 'app-invite-dialog',
  imports: [
    ClipboardModule,
    ReactiveFormsModule,
    MatButtonModule,
    MatDialogModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    RolePicker,
  ],
  templateUrl: './invite.dialog.html',
  styleUrl: './dialog.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class InviteDialog {
  private readonly team = inject(TeamService);
  private readonly origin = inject(DOCUMENT).location.origin;

  protected readonly form = inject(NonNullableFormBuilder).group({
    email: ['', [Validators.required, Validators.email]],
    roles: roleGroup(['analyst']),
  });
  protected readonly sending = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly link = signal<string | null>(null);
  protected readonly copied = signal(false);

  protected async submit(): Promise<void> {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    this.sending.set(true);
    this.error.set(null);
    try {
      const created = await this.team.invite(
        this.form.controls.email.value,
        selectedRoles(this.form.controls.roles),
      );
      this.link.set(created.token ? `${this.origin}/invitacion#${created.token}` : null);
      if (!created.token) {
        this.error.set(
          'La invitación ya existía. Revócala e invita de nuevo para obtener otro enlace.',
        );
      }
    } catch (error) {
      this.error.set(teamErrorMessage(error));
    } finally {
      this.sending.set(false);
    }
  }
}
