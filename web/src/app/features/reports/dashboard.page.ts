import {
  ChangeDetectionStrategy,
  Component,
  computed,
  DestroyRef,
  inject,
  input,
  OnInit,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatSelectModule } from '@angular/material/select';

import { BankAccountView } from '../../api/models/bank-account-view';
import { DashboardView } from '../../api/models/dashboard-view';
import { PeriodView } from '../../api/models/period-view';
import { isFinished, JobTracker } from '../../core/jobs/job-tracker';
import { SessionStore } from '../../core/session/session.store';
import { BankingService } from '../admin/banking.service';
import { dayLabel, monthLabel, REASON_LABELS } from '../matching/labels';
import { ChartCard } from './chart-card.component';
import { ChartRow, percent } from './charts';
import { AccountMonth, ReportsService, reportsErrorMessage } from './reports.service';

const EXPORT_FAILED = 'No pudimos preparar el Excel. Intenta de nuevo.';

const AGE_LABELS: Record<string, string> = {
  '0-7': '0 a 7 días',
  '8-30': '8 a 30 días',
  '31+': 'Más de 30 días',
};

@Component({
  selector: 'app-dashboard-page',
  imports: [MatButtonModule, MatFormFieldModule, MatSelectModule, ChartCard],
  templateUrl: './dashboard.page.html',
  styleUrl: './reports.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DashboardPage implements OnInit {
  private readonly reports = inject(ReportsService);
  private readonly banking = inject(BankingService);
  private readonly jobs = inject(JobTracker);
  private readonly session = inject(SessionStore);
  private readonly destroyRef = inject(DestroyRef);

  readonly cuenta = input<string>();
  readonly mes = input<string>();

  protected readonly accounts = signal<BankAccountView[] | null>(null);
  protected readonly accountId = signal<string | null>(null);
  protected readonly periods = signal<PeriodView[]>([]);
  protected readonly month = signal<AccountMonth | null>(null);
  protected readonly dashboard = signal<DashboardView | null>(null);
  protected readonly error = signal<string | null>(null);
  protected readonly monthLabel = monthLabel;
  protected readonly day = dayLabel;
  protected readonly exporting = signal(false);
  protected readonly download = signal<{ url: string; filename: string } | null>(null);
  protected readonly exportError = signal<string | null>(null);
  protected readonly canExport = computed(() => {
    const roles = this.session.roles();
    return roles.has('analyst') || roles.has('reviewer');
  });

  protected readonly reconciled = computed(() => {
    const view = this.dashboard();
    if (!view) {
      return null;
    }
    const credits = Object.values(view.credits);
    const totalCents = credits.reduce((sum, tally) => sum + tally.cents, 0);
    const totalCount = credits.reduce((sum, tally) => sum + tally.count, 0);
    return {
      byAmount: percent(view.credits.approved.cents, totalCents),
      byCount: percent(view.credits.approved.count, totalCount),
      totalCount,
    };
  });
  protected readonly statusRows = computed<ChartRow[]>(() => {
    const credits = this.dashboard()?.credits;
    if (!credits || Object.values(credits).every((tally) => tally.count === 0)) {
      return [];
    }
    return [
      { label: 'Conciliados', ...credits.approved },
      { label: 'Confirmados', ...credits.confirmed },
      { label: 'Propuestos', ...credits.proposed },
      { label: 'Sin conciliar', ...credits.free },
    ];
  });
  protected readonly pendingRows = computed<ChartRow[]>(() => {
    const pending = this.dashboard()?.pending ?? [];
    if (pending.every((age) => age.count === 0)) {
      return [];
    }
    return pending.map((age) => ({ label: AGE_LABELS[age.bucket], ...age }));
  });
  protected readonly differenceRows = computed<ChartRow[]>(() =>
    (this.dashboard()?.differences ?? []).map((item) => ({
      label: REASON_LABELS[item.reason] ?? item.reason,
      count: item.count,
      cents: item.cents,
    })),
  );

  async ngOnInit(): Promise<void> {
    try {
      const accounts = (await this.banking.accounts()).filter((account) => !account.archived_at);
      this.accounts.set(accounts);
      const wanted = accounts.find((account) => account.id === this.cuenta());
      const account = wanted ?? accounts.at(0);
      if (account) {
        await this.selectAccount(account.id, wanted ? this.mes() : undefined);
      }
    } catch (error) {
      this.error.set(reportsErrorMessage(error));
    }
  }

  protected periodLabel(period: PeriodView): string {
    return `${monthLabel(period.period)}${period.closed ? ' (cerrado)' : ''}`;
  }

  protected async selectAccount(accountId: string, period?: string): Promise<void> {
    this.accountId.set(accountId);
    this.month.set(null);
    this.dashboard.set(null);
    try {
      const periods = await this.reports.periods(accountId);
      this.periods.set(periods);
      const chosen = periods.find((item) => item.period === period) ?? periods.at(0);
      if (chosen) {
        await this.selectPeriod(chosen.period);
      }
    } catch (error) {
      this.error.set(reportsErrorMessage(error));
    }
  }

  protected async exportMonth(): Promise<void> {
    const month = this.month();
    if (!month) {
      return;
    }
    this.exporting.set(true);
    this.download.set(null);
    this.exportError.set(null);
    try {
      const requested = await this.reports.requestExport(month);
      this.follow(requested.job_id, requested.id, month.period);
    } catch (error) {
      this.exporting.set(false);
      this.exportError.set(reportsErrorMessage(error, EXPORT_FAILED));
    }
  }

  private follow(jobId: string, exportId: string, period: string): void {
    let finished = false;
    this.jobs
      .track(jobId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (job) => {
          finished = isFinished(job);
          if (job.status === 'done') {
            this.download.set({
              url: this.reports.exportFileUrl(exportId),
              filename: `conciliacion-${period.slice(0, 7)}.xlsx`,
            });
          } else if (job.status === 'failed') {
            this.exportError.set(EXPORT_FAILED);
          }
        },
        error: (error: unknown) => {
          this.exporting.set(false);
          this.exportError.set(reportsErrorMessage(error, EXPORT_FAILED));
        },
        complete: () => {
          this.exporting.set(false);
          if (!finished) {
            this.exportError.set(
              'El Excel está tardando más de lo normal. Vuelve en unos minutos.',
            );
          }
        },
      });
  }

  protected async selectPeriod(period: string): Promise<void> {
    const accountId = this.accountId();
    if (!accountId) {
      return;
    }
    const month = { accountId, period };
    this.month.set(month);
    this.dashboard.set(null);
    this.download.set(null);
    this.exportError.set(null);
    try {
      const view = await this.reports.dashboard(month);
      if (this.month() === month) {
        this.dashboard.set(view);
        this.error.set(null);
      }
    } catch (error) {
      this.error.set(reportsErrorMessage(error));
    }
  }
}
