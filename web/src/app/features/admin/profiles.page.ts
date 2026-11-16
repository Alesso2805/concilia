import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  OnInit,
  signal,
} from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatDialog } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatTableModule } from '@angular/material/table';
import { RouterLink } from '@angular/router';
import { firstValueFrom } from 'rxjs';

import { BankAccountView } from '../../api/models/bank-account-view';
import { BankingService, ProfileView, bankingErrorMessage } from './banking.service';
import { ConfirmData, ConfirmDialog } from './confirm.dialog';
import { KIND_LABELS } from './profile-form';

@Component({
  selector: 'app-profiles-page',
  imports: [
    RouterLink,
    MatButtonModule,
    MatIconModule,
    MatProgressBarModule,
    MatSlideToggleModule,
    MatTableModule,
  ],
  templateUrl: './profiles.page.html',
  styleUrl: './admin-page.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ProfilesPage implements OnInit {
  private readonly banking = inject(BankingService);
  private readonly dialog = inject(MatDialog);

  protected readonly profiles = signal<ProfileView[] | null>(null);
  protected readonly accounts = signal<BankAccountView[]>([]);
  protected readonly showArchived = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly columns = ['name', 'kind', 'account', 'status', 'actions'];
  protected readonly visible = computed(() =>
    (this.profiles() ?? []).filter((profile) => this.showArchived() || !profile.archived_at),
  );

  ngOnInit(): void {
    void this.reload();
  }

  protected kindOf(profile: ProfileView): string {
    return KIND_LABELS[profile.kind];
  }

  protected accountOf(profile: ProfileView): string {
    if (profile.kind !== 'bank_statement') {
      return '—';
    }
    const account = this.accounts().find((candidate) => candidate.id === profile.bank_account_id);
    return account ? `${account.alias} ···· ${account.number_last4}` : '—';
  }

  protected async archive(profile: ProfileView): Promise<void> {
    const data: ConfirmData = {
      title: `¿Archivar «${profile.name}»?`,
      message: 'Ya no se ofrecerá al importar. Lo que ya se importó con este perfil se conserva.',
      action: 'Archivar',
      run: () => this.banking.archiveProfile(profile.id),
    };
    const changed = await firstValueFrom(
      this.dialog.open<ConfirmDialog, ConfirmData, boolean>(ConfirmDialog, { data }).afterClosed(),
    );
    if (changed) {
      await this.reload();
    }
  }

  private async reload(): Promise<void> {
    try {
      const [profiles, accounts] = await Promise.all([
        this.banking.profiles(),
        this.banking.accounts(),
      ]);
      this.accounts.set(accounts);
      this.profiles.set(profiles);
      this.error.set(null);
    } catch (error) {
      this.error.set(bankingErrorMessage(error));
    }
  }
}
