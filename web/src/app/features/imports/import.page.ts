import { DatePipe } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  input,
  OnInit,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatButtonModule } from '@angular/material/button';
import { MatDialog } from '@angular/material/dialog';
import { MatPaginatorIntl, MatPaginatorModule, PageEvent } from '@angular/material/paginator';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatTableModule } from '@angular/material/table';
import { MatTabsModule } from '@angular/material/tabs';
import { RouterLink } from '@angular/router';
import {
  Observable,
  filter,
  firstValueFrom,
  from,
  switchMap,
  takeUntil,
  takeWhile,
  timer,
} from 'rxjs';

import { ErrorRowView } from '../../api/models/error-row-view';
import { ImportSummaryView } from '../../api/models/import-summary-view';
import { ReceivableRowView } from '../../api/models/receivable-row-view';
import { RowPageView } from '../../api/models/row-page-view';
import { StatementRowView } from '../../api/models/statement-row-view';
import { formatPen } from '../../core/format/amounts';
import { GIVE_UP_AFTER_MS, JobTracker, POLL_INTERVAL_MS } from '../../core/jobs/job-tracker';
import { KeysetPaginatorIntl, keysetLength } from '../../core/paging/keyset';
import { ConfirmData, ConfirmDialog } from '../admin/confirm.dialog';
import {
  ImportsService,
  PreviewStatus,
  ROW_MESSAGES,
  codeMessage,
  fileErrorMessage,
  importErrorMessage,
} from './imports.service';
import { KIND_TEXTS, KindTexts, PreviewTab, STATUS_LABELS } from './labels';
import { ReasonData, ReasonDialog } from './reason.dialog';

const PAGE_SIZE = 25;
const PROCESSING = new Set(['uploaded', 'parsing']);

@Component({
  selector: 'app-import-page',
  imports: [
    DatePipe,
    RouterLink,
    MatButtonModule,
    MatPaginatorModule,
    MatProgressBarModule,
    MatTableModule,
    MatTabsModule,
  ],
  providers: [{ provide: MatPaginatorIntl, useClass: KeysetPaginatorIntl }],
  templateUrl: './import.page.html',
  styleUrl: './imports.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ImportPage implements OnInit {
  private readonly imports = inject(ImportsService);
  private readonly jobs = inject(JobTracker);
  private readonly dialog = inject(MatDialog);
  private readonly destroyRef = inject(DestroyRef);

  readonly id = input.required<string>();
  readonly trabajo = input<string>();

  protected readonly summary = signal<ImportSummaryView | null>(null);
  protected readonly progress = signal(0);
  protected readonly waiting = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly tab = signal<PreviewStatus>('ok');
  protected readonly rows = signal<{ status: PreviewStatus; page: RowPageView } | null>(null);
  protected readonly pageIndex = signal(0);
  protected readonly pageSize = PAGE_SIZE;
  protected readonly texts = computed<KindTexts>(
    () => KIND_TEXTS[this.summary()?.file.kind ?? 'bank_statement'],
  );
  protected readonly length = computed(() =>
    keysetLength(this.pageIndex(), PAGE_SIZE, this.rows()?.page.has_next ?? false),
  );
  protected readonly processing = computed(() =>
    PROCESSING.has(this.summary()?.file.status ?? 'uploaded'),
  );

  async ngOnInit(): Promise<void> {
    await this.reload();
    const job = this.trabajo();
    if (this.processing()) {
      if (job) {
        this.follow(job);
      } else {
        this.pollSummary();
      }
    }
  }

  protected statusLabel(summary: ImportSummaryView): string {
    return STATUS_LABELS[summary.file.status];
  }

  protected tabLabel(tab: PreviewTab): string {
    return `${tab.label} (${this.summary()?.counts[tab.status] ?? 0})`;
  }

  protected fileError(summary: ImportSummaryView): string {
    return fileErrorMessage(summary.file.error_code);
  }

  protected amount(row: StatementRowView | ReceivableRowView): string {
    return formatPen(row.amount_cents);
  }

  protected change(row: ReceivableRowView): string {
    if (row.conflict === 'cancelled') {
      return 'El cobro está anulado';
    }
    if (row.conflict === 'active_matches') {
      return 'El cobro está en una conciliación';
    }
    if (row.action === 'update' && row.previous_due_on && row.previous_amount_cents !== null) {
      const due = row.previous_due_on.split('-').reverse().join('/');
      return `Antes: vence ${due}, ${formatPen(row.previous_amount_cents)}`;
    }
    return row.action === 'unchanged' ? 'Sin cambios' : 'Nuevo';
  }

  protected reason(row: ErrorRowView): string {
    return ROW_MESSAGES[row.error_code] ?? row.error_code;
  }

  protected rowsFor(status: PreviewStatus): RowPageView | null {
    const rows = this.rows();
    return rows?.status === status ? rows.page : null;
  }

  protected columnsFor(status: PreviewStatus): string[] {
    if (status === 'error') {
      return ['row', 'reason', 'cells'];
    }
    return this.summary()?.file.kind === 'receivables'
      ? ['row', 'document', 'customer', 'due', 'amount', 'change']
      : ['row', 'date', 'description', 'operation', 'amount'];
  }

  protected async selectTab(index: number): Promise<void> {
    this.tab.set(this.texts().tabs[index].status);
    this.pageIndex.set(0);
    this.rows.set(null);
    await this.loadRows({});
  }

  protected async turn(event: PageEvent): Promise<void> {
    const rows = this.rows()?.page.rows ?? [];
    const forward = event.pageIndex > this.pageIndex();
    this.pageIndex.set(event.pageIndex);
    await this.loadRows(
      forward ? { after: rows.at(-1)?.row_number } : { before: rows.at(0)?.row_number },
    );
  }

  protected async confirm(): Promise<void> {
    this.error.set(null);
    try {
      this.follow(await this.imports.confirm(this.id()));
    } catch (error) {
      this.error.set(importErrorMessage(error));
    }
  }

  protected async discard(): Promise<void> {
    const data: ConfirmData = {
      title: '¿Descartar esta vista previa?',
      message: `No se guardará ${this.texts().nothing}. Podrás volver a subir el archivo.`,
      action: 'Descartar',
      run: () => this.imports.discard(this.id()),
      describeError: importErrorMessage,
    };
    await this.afterDialog(
      this.dialog.open<ConfirmDialog, ConfirmData, boolean>(ConfirmDialog, { data }).afterClosed(),
    );
  }

  protected async voidImport(): Promise<void> {
    const data: ReasonData = {
      title: '¿Anular esta importación?',
      message: this.texts().voidEffect,
      action: 'Anular importación',
      run: (reason) => this.imports.void(this.id(), reason),
    };
    await this.afterDialog(
      this.dialog.open<ReasonDialog, ReasonData, boolean>(ReasonDialog, { data }).afterClosed(),
    );
  }

  private async afterDialog(closed: Observable<boolean | undefined>): Promise<void> {
    if (await firstValueFrom(closed)) {
      await this.reload();
    }
  }

  private follow(jobId: string): void {
    this.waiting.set(true);
    let finished = false;
    this.jobs
      .track(jobId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (job) => {
          this.progress.set(job.progress);
          if (job.status === 'failed') {
            this.error.set(codeMessage(job.error_code));
          }
          finished = job.status === 'done' || job.status === 'failed';
        },
        error: (error: unknown) => {
          this.waiting.set(false);
          this.error.set(importErrorMessage(error));
        },
        complete: () => {
          this.waiting.set(false);
          if (!finished) {
            this.error.set('El proceso está tardando más de lo normal. Vuelve en unos minutos.');
          }
          void this.reload();
        },
      });
  }

  private pollSummary(): void {
    this.waiting.set(true);
    timer(POLL_INTERVAL_MS, POLL_INTERVAL_MS)
      .pipe(
        switchMap(() => from(this.imports.summary(this.id()))),
        takeWhile((summary) => PROCESSING.has(summary.file.status), true),
        filter((summary) => !PROCESSING.has(summary.file.status)),
        takeUntil(timer(GIVE_UP_AFTER_MS)),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe({
        next: () => void this.reload(),
        complete: () => this.waiting.set(false),
      });
  }

  private async reload(): Promise<void> {
    try {
      const summary = await this.imports.summary(this.id());
      this.summary.set(summary);
      if (summary.file.status === 'previewed') {
        await this.loadRows({});
      }
    } catch (error) {
      this.error.set(importErrorMessage(error));
    }
  }

  private async loadRows(cursor: { after?: number; before?: number }): Promise<void> {
    try {
      const status = this.tab();
      const page = await this.imports.rows(this.id(), status, cursor);
      if (status === this.tab()) {
        this.rows.set({ status, page });
      }
    } catch (error) {
      this.error.set(importErrorMessage(error));
    }
  }
}
