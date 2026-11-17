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
import { NgTemplateOutlet } from '@angular/common';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { firstValueFrom } from 'rxjs';
import { FormControl, FormGroup, ReactiveFormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatDialog } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatPaginatorIntl, MatPaginatorModule, PageEvent } from '@angular/material/paginator';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSelectModule } from '@angular/material/select';
import { MatTableModule } from '@angular/material/table';
import { MatTabsModule } from '@angular/material/tabs';
import { RouterLink } from '@angular/router';

import { BankAccountView } from '../../api/models/bank-account-view';
import { CreditView } from '../../api/models/credit-view';
import { UsageView } from '../../api/models/usage-view';
import { CountsView } from '../../api/models/counts-view';
import { CreditPageView } from '../../api/models/credit-page-view';
import { EngineRunView } from '../../api/models/engine-run-view';
import { MatchPageView } from '../../api/models/match-page-view';
import { MatchRowView } from '../../api/models/match-row-view';
import { PeriodView } from '../../api/models/period-view';
import { formatPen, parseSoles } from '../../core/format/amounts';
import { isFinished, JobTracker } from '../../core/jobs/job-tracker';
import { KeysetPaginatorIntl, keysetLength } from '../../core/paging/keyset';
import { SessionStore } from '../../core/session/session.store';
import { BankingService } from '../admin/banking.service';
import { AiService } from '../ai/ai.service';
import { SuggestionDialog, SuggestionDialogData } from '../ai/suggestion.dialog';
import { PeriodsService } from '../periods/periods.service';
import { ReopenPeriodDialog } from '../periods/reopen-period.dialog';
import {
  dayLabel,
  EMPTY_TABS,
  FILTERED_HINT,
  monthLabel,
  RULE_LABELS,
  RULE_NAMES,
  TABS,
} from './labels';
import { MatchDetailDialog } from './match-detail.dialog';
import { ScoreMeter } from './score-meter.component';
import {
  Cursor,
  InboxFilters,
  InboxTab,
  matchingCodeMessage,
  MatchingService,
  matchingErrorMessage,
  MatchTab,
  Month,
  NO_FILTERS,
  Rule,
} from './matching.service';

const PAGE_SIZE = 25;
const RULES = Object.keys(RULE_LABELS) as Rule[];

function batchNotice(action: 'confirm' | 'approve', decided: number, skipped: number): string {
  const one = decided === 1;
  const verb =
    action === 'confirm' ? (one ? 'confirmó' : 'confirmaron') : one ? 'aprobó' : 'aprobaron';
  const left =
    skipped === 0
      ? ''
      : ` ${skipped === 1 ? 'Una queda' : `${skipped} quedan`} para otra persona porque tú las creaste o confirmaste.`;
  return `Se ${verb} ${decided} ${one ? 'coincidencia' : 'coincidencias'}.${left}`;
}

type Loaded = { tab: 'free'; view: CreditPageView } | { tab: MatchTab; view: MatchPageView };

@Component({
  selector: 'app-inbox-page',
  imports: [
    NgTemplateOutlet,
    ReactiveFormsModule,
    MatButtonModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatPaginatorModule,
    MatProgressBarModule,
    MatSelectModule,
    MatTableModule,
    MatTabsModule,
    RouterLink,
    ScoreMeter,
  ],
  providers: [{ provide: MatPaginatorIntl, useClass: KeysetPaginatorIntl }],
  templateUrl: './inbox.page.html',
  styleUrl: './inbox.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class InboxPage implements OnInit {
  private readonly matching = inject(MatchingService);
  private readonly banking = inject(BankingService);
  private readonly periodsApi = inject(PeriodsService);
  private readonly ai = inject(AiService);
  private readonly jobs = inject(JobTracker);
  private readonly dialog = inject(MatDialog);
  private readonly session = inject(SessionStore);
  private readonly destroyRef = inject(DestroyRef);

  readonly cuenta = input<string>();
  readonly mes = input<string>();

  protected readonly tabs = TABS;
  protected readonly matchColumns = [
    'date',
    'description',
    'documents',
    'rule',
    'score',
    'amount',
    'difference',
    'actions',
  ];
  protected readonly rules = RULES;
  protected readonly ruleLabels = RULE_LABELS;
  protected readonly pageSize = PAGE_SIZE;
  protected readonly pen = formatPen;
  protected readonly day = dayLabel;
  protected readonly monthLabel = monthLabel;

  protected readonly accounts = signal<BankAccountView[] | null>(null);
  protected readonly accountId = signal<string | null>(null);
  protected readonly periods = signal<PeriodView[]>([]);
  protected readonly month = signal<Month | null>(null);
  protected readonly counts = signal<CountsView | null>(null);
  protected readonly tab = signal<InboxTab>('proposed');
  protected readonly filters = signal<InboxFilters>(NO_FILTERS);
  protected readonly page = signal<Loaded | null>(null);
  protected readonly pageIndex = signal(0);
  protected readonly running = signal(false);
  protected readonly progress = signal(0);
  protected readonly notice = signal<string | null>(null);
  protected readonly error = signal<string | null>(null);

  protected readonly tabIndex = computed(() => TABS.findIndex((item) => item.tab === this.tab()));
  protected readonly closed = computed(
    () => this.periods().find((item) => item.period === this.month()?.period)?.closed ?? false,
  );
  protected readonly canRun = computed(
    () =>
      this.session.roles().has('analyst') &&
      this.month() !== null &&
      !this.closed() &&
      !this.running(),
  );
  protected readonly batch = computed(() => {
    const roles = this.session.roles();
    if (this.closed() || this.running() || this.counts()?.[this.tab()] === 0) {
      return null;
    }
    if (this.tab() === 'proposed' && roles.has('analyst')) {
      return {
        action: 'confirm' as const,
        label: 'Confirmar todas las de puntaje 100',
        hint: 'Las propuestas con puntaje 100 se pueden confirmar en un solo paso.',
      };
    }
    if (this.tab() === 'confirmed' && roles.has('reviewer')) {
      return {
        action: 'approve' as const,
        label: 'Aprobar todas las de puntaje 100',
        hint: 'Las de puntaje 100 se aprueban en un paso; las que creaste o confirmaste quedan para otra persona.',
      };
    }
    return null;
  });
  protected readonly filtered = computed(() => {
    const filters = this.filters();
    return (
      filters.rule !== null ||
      filters.minScore !== null ||
      filters.minAmountCents !== null ||
      filters.maxAmountCents !== null
    );
  });
  protected readonly accountLabel = computed(() => {
    const account = this.accounts()?.find((item) => item.id === this.accountId());
    return account ? `${account.bank} · ${account.alias} ···${account.number_last4}` : null;
  });
  protected readonly batching = signal(false);
  protected readonly aiUsage = signal<UsageView | null>(null);
  protected readonly canAskAi = computed(
    () =>
      this.session.roles().has('analyst') && !this.closed() && (this.aiUsage()?.available ?? false),
  );
  protected readonly creditColumns = computed(() =>
    this.canAskAi()
      ? ['date', 'description', 'operation', 'amount', 'ai']
      : ['date', 'description', 'operation', 'amount'],
  );
  protected readonly closing = signal(false);
  protected readonly canClose = computed(
    () =>
      this.session.roles().has('reviewer') &&
      this.month() !== null &&
      !this.closed() &&
      !this.running(),
  );
  protected readonly canReopen = computed(
    () => this.session.roles().has('reviewer') && this.closed(),
  );
  protected readonly length = computed(() =>
    keysetLength(this.pageIndex(), PAGE_SIZE, this.page()?.view.has_next ?? false),
  );
  protected readonly filterForm = new FormGroup({
    rule: new FormControl<Rule | null>(null),
    minScore: new FormControl('', { nonNullable: true }),
    minAmount: new FormControl('', { nonNullable: true }),
    maxAmount: new FormControl('', { nonNullable: true }),
  });

  async ngOnInit(): Promise<void> {
    void this.loadAiUsage();
    try {
      const accounts = (await this.banking.accounts()).filter((account) => !account.archived_at);
      this.accounts.set(accounts);
      const wanted = accounts.find((account) => account.id === this.cuenta());
      const account = wanted ?? accounts.at(0);
      if (account) {
        await this.selectAccount(account.id, wanted ? this.mes() : undefined);
      }
    } catch (error) {
      this.error.set(matchingErrorMessage(error));
    }
  }

  protected empty(tab: InboxTab): { title: string; hint: string } {
    const state = EMPTY_TABS[tab];
    return this.filtered() ? { title: state.title, hint: FILTERED_HINT } : state;
  }

  protected periodLabel(period: PeriodView): string {
    return `${monthLabel(period.period)}${period.closed ? ' (cerrado)' : ''}`;
  }

  protected creditPage(): CreditPageView | null {
    const page = this.page();
    return page?.tab === 'free' ? page.view : null;
  }

  protected matchPage(tab: InboxTab): MatchPageView | null {
    const page = this.page();
    return page && page.tab !== 'free' && page.tab === tab ? page.view : null;
  }

  protected ruleOf(match: MatchRowView): string {
    return match.rule ? RULE_NAMES[match.rule] : match.source === 'ai' ? 'IA' : 'Manual';
  }

  protected async selectAccount(accountId: string, period?: string): Promise<void> {
    this.accountId.set(accountId);
    this.month.set(null);
    this.counts.set(null);
    this.page.set(null);
    try {
      const periods = await this.matching.periods(accountId);
      this.periods.set(periods);
      const chosen = periods.find((item) => item.period === period) ?? periods.at(0);
      if (chosen) {
        await this.selectPeriod(chosen.period);
      }
    } catch (error) {
      this.error.set(matchingErrorMessage(error));
    }
  }

  protected async selectPeriod(period: string): Promise<void> {
    const accountId = this.accountId();
    if (!accountId) {
      return;
    }
    this.month.set({ accountId, period });
    this.notice.set(null);
    await this.refresh();
  }

  protected async selectTab(index: number): Promise<void> {
    this.tab.set(TABS[index].tab);
    await this.restart();
  }

  protected async applyFilters(): Promise<void> {
    const value = this.filterForm.getRawValue();
    const minScore = value.minScore.trim() === '' ? null : Number(value.minScore);
    const minAmount = value.minAmount.trim() === '' ? null : parseSoles(value.minAmount);
    const maxAmount = value.maxAmount.trim() === '' ? null : parseSoles(value.maxAmount);
    const invalid =
      (minScore !== null && !(Number.isInteger(minScore) && minScore >= 0 && minScore <= 100)) ||
      (value.minAmount.trim() !== '' && minAmount === null) ||
      (value.maxAmount.trim() !== '' && maxAmount === null);
    if (invalid) {
      this.error.set('Revisa los filtros: el puntaje va de 0 a 100 y los montos son en soles.');
      return;
    }
    this.error.set(null);
    this.filters.set({
      rule: value.rule,
      minScore,
      minAmountCents: minAmount,
      maxAmountCents: maxAmount,
    });
    await this.restart();
  }

  protected async clearFilters(): Promise<void> {
    this.filterForm.reset();
    this.filters.set(NO_FILTERS);
    this.error.set(null);
    await this.restart();
  }

  protected async turn(event: PageEvent): Promise<void> {
    const view = this.page()?.view;
    if (!view) {
      return;
    }
    const forward = event.pageIndex > this.pageIndex();
    this.pageIndex.set(event.pageIndex);
    await this.load(forward ? { after: view.next_cursor } : { before: view.previous_cursor });
  }

  protected async open(match: MatchRowView): Promise<void> {
    const closed = this.dialog
      .open<MatchDetailDialog, string, boolean>(MatchDetailDialog, {
        data: match.id,
        autoFocus: 'dialog',
        panelClass: 'app-wide-dialog',
      })
      .afterClosed();
    if (await firstValueFrom(closed)) {
      await this.refresh();
    }
  }

  protected async decideBatch(action: 'confirm' | 'approve'): Promise<void> {
    const month = this.month();
    if (!month) {
      return;
    }
    this.batching.set(true);
    this.notice.set(null);
    this.error.set(null);
    try {
      const result = await this.matching.decideBatch(month, action);
      this.notice.set(batchNotice(action, result.decided, result.skipped));
      await this.refresh();
    } catch (error) {
      this.error.set(matchingErrorMessage(error));
    } finally {
      this.batching.set(false);
    }
  }

  protected async askAi(credit: CreditView): Promise<void> {
    const usage = this.aiUsage();
    if (!usage) {
      return;
    }
    const accepted = await firstValueFrom(
      this.dialog
        .open<SuggestionDialog, SuggestionDialogData, boolean>(SuggestionDialog, {
          data: { credit, usage },
          autoFocus: 'dialog',
          width: 'min(720px, 100vw)',
        })
        .afterClosed(),
    );
    void this.loadAiUsage();
    if (accepted) {
      this.notice.set('Se creó una propuesta a partir de la sugerencia de la IA.');
      await this.refresh();
    }
  }

  private async loadAiUsage(): Promise<void> {
    try {
      this.aiUsage.set(await this.ai.usage());
    } catch {
      this.aiUsage.set(null);
    }
  }

  protected async closePeriod(): Promise<void> {
    const month = this.month();
    if (!month) {
      return;
    }
    await this.changePeriod(
      () => this.periodsApi.close(month),
      `Cerraste ${monthLabel(month.period)}.`,
    );
  }

  protected async reopenPeriod(): Promise<void> {
    const month = this.month();
    if (!month) {
      return;
    }
    const reason = await firstValueFrom(
      this.dialog
        .open<ReopenPeriodDialog, string, string>(ReopenPeriodDialog, {
          data: monthLabel(month.period),
          autoFocus: 'first-tabbable',
        })
        .afterClosed(),
    );
    if (!reason) {
      return;
    }
    await this.changePeriod(
      () => this.periodsApi.reopen(month, reason),
      `Reabriste ${monthLabel(month.period)}.`,
    );
  }

  private async changePeriod(change: () => Promise<unknown>, done: string): Promise<void> {
    const month = this.month();
    if (!month) {
      return;
    }
    this.closing.set(true);
    this.notice.set(null);
    this.error.set(null);
    try {
      await change();
      this.periods.set(await this.matching.periods(month.accountId));
      this.notice.set(done);
      await this.refresh();
    } catch (error) {
      this.error.set(matchingErrorMessage(error));
    } finally {
      this.closing.set(false);
    }
  }

  protected async runEngine(): Promise<void> {
    const month = this.month();
    if (!month) {
      return;
    }
    this.notice.set(null);
    this.error.set(null);
    try {
      this.follow(await this.matching.runEngine(month));
    } catch (error) {
      this.error.set(matchingErrorMessage(error));
    }
  }

  private follow(run: EngineRunView): void {
    if (!run.job_id) {
      return;
    }
    this.running.set(true);
    this.progress.set(0);
    let finished = false;
    this.jobs
      .track(run.job_id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (job) => {
          this.progress.set(job.progress);
          if (job.status === 'failed') {
            this.error.set(matchingCodeMessage(job.error_code));
          }
          finished = isFinished(job);
        },
        error: (error: unknown) => {
          this.running.set(false);
          this.error.set(matchingErrorMessage(error));
        },
        complete: () => {
          this.running.set(false);
          if (!finished) {
            this.error.set('El motor está tardando más de lo normal. Vuelve en unos minutos.');
            return;
          }
          void this.afterRun(run.id);
        },
      });
  }

  private async afterRun(runId: string): Promise<void> {
    try {
      const run = await this.matching.run(runId);
      if (run.proposals_count !== null) {
        const count = run.proposals_count;
        this.notice.set(
          count === 1
            ? 'El motor propuso 1 coincidencia.'
            : `El motor propuso ${count} coincidencias.`,
        );
      }
      this.tab.set('proposed');
      await this.refresh();
    } catch (error) {
      this.error.set(matchingErrorMessage(error));
    }
  }

  private async refresh(): Promise<void> {
    const month = this.month();
    if (!month) {
      return;
    }
    try {
      this.counts.set(await this.matching.counts(month));
    } catch (error) {
      this.error.set(matchingErrorMessage(error));
    }
    await this.restart();
  }

  private async restart(): Promise<void> {
    this.pageIndex.set(0);
    this.page.set(null);
    await this.load({});
  }

  private async load(cursor: Cursor): Promise<void> {
    const month = this.month();
    if (!month) {
      return;
    }
    const tab = this.tab();
    try {
      const loaded: Loaded =
        tab === 'free'
          ? { tab, view: await this.matching.credits(month, this.filters(), cursor) }
          : { tab, view: await this.matching.matches(month, tab, this.filters(), cursor) };
      if (tab === this.tab() && month === this.month()) {
        this.page.set(loaded);
      }
    } catch (error) {
      this.error.set(matchingErrorMessage(error));
    }
  }
}
