import { DatePipe } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  OnInit,
  signal,
} from '@angular/core';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatDialog } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatPaginatorIntl, MatPaginatorModule, PageEvent } from '@angular/material/paginator';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatTableModule } from '@angular/material/table';
import { MatTabsModule } from '@angular/material/tabs';
import { firstValueFrom } from 'rxjs';

import { ReceivablePageView } from '../../api/models/receivable-page-view';
import { ReceivableView } from '../../api/models/receivable-view';
import { formatPen } from '../../core/format/amounts';
import { KeysetPaginatorIntl, keysetLength } from '../../core/paging/keyset';
import { SessionStore } from '../../core/session/session.store';
import { ImportsService, importErrorMessage } from './imports.service';
import { ReasonData, ReasonDialog } from './reason.dialog';

const PAGE_SIZE = 20;
const TABS = [
  { cancelled: false, label: 'Vigentes' },
  { cancelled: true, label: 'Anulados' },
] as const;

interface Cursor {
  after?: string | null;
  before?: string | null;
}

@Component({
  selector: 'app-receivables-page',
  imports: [
    DatePipe,
    ReactiveFormsModule,
    MatButtonModule,
    MatFormFieldModule,
    MatInputModule,
    MatPaginatorModule,
    MatProgressBarModule,
    MatTableModule,
    MatTabsModule,
  ],
  providers: [{ provide: MatPaginatorIntl, useClass: KeysetPaginatorIntl }],
  templateUrl: './receivables.page.html',
  styleUrl: './imports.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ReceivablesPage implements OnInit {
  private readonly imports = inject(ImportsService);
  private readonly dialog = inject(MatDialog);
  private readonly session = inject(SessionStore);

  protected readonly tabs = TABS;
  protected readonly cancelled = signal(false);
  protected readonly document = signal<string | null>(null);
  protected readonly page = signal<{ cancelled: boolean; view: ReceivablePageView } | null>(null);
  protected readonly pageIndex = signal(0);
  protected readonly error = signal<string | null>(null);
  protected readonly pageSize = PAGE_SIZE;
  protected readonly length = computed(() =>
    keysetLength(this.pageIndex(), PAGE_SIZE, this.page()?.view.has_next ?? false),
  );
  protected readonly canCancel = computed(() => this.session.roles().has('analyst'));
  protected readonly search = new FormGroup({
    document: new FormControl('', { nonNullable: true, validators: Validators.maxLength(40) }),
  });

  async ngOnInit(): Promise<void> {
    await this.load({});
  }

  protected pageFor(cancelled: boolean): ReceivablePageView | null {
    const page = this.page();
    return page?.cancelled === cancelled ? page.view : null;
  }

  protected columnsFor(cancelled: boolean): string[] {
    if (cancelled) {
      return ['document', 'customer', 'due', 'amount', 'cancelledAt', 'reason'];
    }
    const columns = ['document', 'customer', 'taxId', 'issued', 'due', 'amount'];
    return this.canCancel() ? [...columns, 'actions'] : columns;
  }

  protected amount(receivable: ReceivableView): string {
    return formatPen(receivable.amount_cents);
  }

  protected async find(): Promise<void> {
    const document = this.search.controls.document.value.trim();
    this.document.set(document || null);
    await this.restart();
  }

  protected async clear(): Promise<void> {
    this.search.reset();
    this.document.set(null);
    await this.restart();
  }

  protected async selectTab(index: number): Promise<void> {
    this.cancelled.set(TABS[index].cancelled);
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

  protected async cancel(receivable: ReceivableView): Promise<void> {
    const data: ReasonData = {
      title: `¿Anular el cobro ${receivable.doc_number}?`,
      message:
        'Dejará de figurar como pendiente y no podrá conciliarse. Lo ya aprobado se conserva.',
      action: 'Anular cobro',
      run: (reason) => this.imports.cancelReceivable(receivable.id, reason),
    };
    const closed = this.dialog
      .open<ReasonDialog, ReasonData, boolean>(ReasonDialog, { data })
      .afterClosed();
    if (await firstValueFrom(closed)) {
      await this.restart();
    }
  }

  private async restart(): Promise<void> {
    this.pageIndex.set(0);
    this.page.set(null);
    await this.load({});
  }

  private async load(cursor: Cursor): Promise<void> {
    const cancelled = this.cancelled();
    try {
      const view = await this.imports.receivables({
        cancelled,
        document: this.document(),
        ...cursor,
      });
      if (cancelled === this.cancelled()) {
        this.page.set({ cancelled, view });
        this.error.set(null);
      }
    } catch (error) {
      this.error.set(importErrorMessage(error));
    }
  }
}
