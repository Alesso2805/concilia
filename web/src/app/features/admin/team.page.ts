import { ComponentType } from '@angular/cdk/portal';
import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, inject, OnInit, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatDialog } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatTableModule } from '@angular/material/table';
import { firstValueFrom } from 'rxjs';

import { InvitationView } from '../../api/models/invitation-view';
import { MemberView } from '../../api/models/member-view';
import { TeamView } from '../../api/models/team-view';
import { roleLabel } from '../../core/session/roles';
import { InviteDialog } from './invite.dialog';
import { RemovalDialog, RolesDialog } from './member.dialogs';
import { TeamService, teamErrorMessage } from './team.service';

@Component({
  selector: 'app-team-page',
  imports: [DatePipe, MatButtonModule, MatIconModule, MatProgressBarModule, MatTableModule],
  templateUrl: './team.page.html',
  styleUrl: './team.page.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TeamPage implements OnInit {
  private readonly service = inject(TeamService);
  private readonly dialog = inject(MatDialog);

  protected readonly team = signal<TeamView | null>(null);
  protected readonly error = signal<string | null>(null);
  protected readonly memberColumns = ['name', 'email', 'roles', 'actions'];
  protected readonly invitationColumns = ['email', 'roles', 'expires', 'actions'];

  ngOnInit(): void {
    void this.reload();
  }

  protected roles(roles: readonly string[]): string {
    return roles.map(roleLabel).join(', ');
  }

  protected invite(): Promise<void> {
    return this.openAndReload(InviteDialog, undefined);
  }

  protected editRoles(member: MemberView): Promise<void> {
    return this.openAndReload(RolesDialog, member);
  }

  protected remove(member: MemberView): Promise<void> {
    return this.openAndReload(RemovalDialog, member);
  }

  protected async revoke(invitation: InvitationView): Promise<void> {
    try {
      await this.service.revoke(invitation.id);
    } catch (error) {
      this.error.set(teamErrorMessage(error));
    }
    await this.reload();
  }

  private async openAndReload<T, D>(component: ComponentType<T>, data: D): Promise<void> {
    const changed = await firstValueFrom(
      this.dialog
        .open<T, D, boolean>(component, { data, autoFocus: 'first-tabbable' })
        .afterClosed(),
    );
    if (changed) {
      await this.reload();
    }
  }

  private async reload(): Promise<void> {
    try {
      this.team.set(await this.service.load());
      this.error.set(null);
    } catch (error) {
      this.error.set(teamErrorMessage(error));
    }
  }
}
