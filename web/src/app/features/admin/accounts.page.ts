import { ComponentType } from '@angular/cdk/portal';
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
import { firstValueFrom } from 'rxjs';

import { BankAccountView } from '../../api/models/bank-account-view';
import { AccountDialog } from './account.dialog';
import { BankingService, bankingErrorMessage } from './banking.service';
import { ConfirmData, ConfirmDialog } from './confirm.dialog';

@Component({
  selector: 'app-accounts-page',
  imports: [
    MatButtonModule,
    MatIconModule,
    MatProgressBarModule,
    MatSlideToggleModule,
    MatTableModule,
  ],
  templateUrl: './accounts.page.html',
  styleUrl: './admin-page.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AccountsPage implements OnInit {
  private readonly banking = inject(BankingService);
  private readonly dialog = inject(MatDialog);

  protected readonly accounts = signal<BankAccountView[] | null>(null);
  protected readonly showArchived = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly visible = computed(() =>
    (this.accounts() ?? []).filter((account) => this.showArchived() || !account.archived_at),
  );
  protected readonly columns = ['bank', 'alias', 'number', 'status', 'actions'];

  ngOnInit(): void {
    void this.reload();
  }

  protected create(): Promise<void> {
    return this.open(AccountDialog, null);
  }

  protected edit(account: BankAccountView): Promise<void> {
    return this.open(AccountDialog, account);
  }

  protected archive(account: BankAccountView): Promise<void> {
    return this.open<ConfirmDialog, ConfirmData>(ConfirmDialog, {
      title: `¿Archivar «${account.alias}»?`,
      message:
        'No se podrán importar más extractos en esta cuenta. Lo ya importado y conciliado se conserva.',
      action: 'Archivar',
      run: () => this.banking.archiveAccount(account.id),
    });
  }

  private async open<T, D>(component: ComponentType<T>, data: D): Promise<void> {
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
      this.accounts.set(await this.banking.accounts());
      this.error.set(null);
    } catch (error) {
      this.error.set(bankingErrorMessage(error));
    }
  }
}
