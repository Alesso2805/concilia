import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  input,
  OnInit,
  signal,
} from '@angular/core';
import { FormControl, FormGroup, ReactiveFormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatPaginatorIntl, MatPaginatorModule, PageEvent } from '@angular/material/paginator';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSelectModule } from '@angular/material/select';
import { MatTableModule } from '@angular/material/table';
import { Router, RouterLink } from '@angular/router';

import { CreditPageView } from '../../api/models/credit-page-view';
import { CreditView } from '../../api/models/credit-view';
import { OpenReceivableView } from '../../api/models/open-receivable-view';
import { formatPen, parseSoles, solesInput } from '../../core/format/amounts';
import { KeysetPaginatorIntl, keysetLength } from '../../core/paging/keyset';
import { dayLabel, monthLabel, REASON_LABELS } from './labels';
import {
  Cursor,
  Decision,
  MatchingService,
  matchingErrorMessage,
  Month,
  NO_FILTERS,
} from './matching.service';

type Reason = NonNullable<Decision['difference_reason']>;

interface Applied {
  receivable: OpenReceivableView;
  amount: string;
}

const PAGE_SIZE = 25;
const REASONS = Object.keys(REASON_LABELS) as Reason[];

@Component({
  selector: 'app-manual-page',
  imports: [
    ReactiveFormsModule,
    RouterLink,
    MatButtonModule,
    MatCheckboxModule,
    MatFormFieldModule,
    MatInputModule,
    MatPaginatorModule,
    MatProgressBarModule,
    MatSelectModule,
    MatTableModule,
  ],
  providers: [{ provide: MatPaginatorIntl, useClass: KeysetPaginatorIntl }],
  templateUrl: './manual.page.html',
  styleUrl: './inbox.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ManualPage implements OnInit {
  private readonly matching = inject(MatchingService);
  private readonly router = inject(Router);

  readonly cuenta = input.required<string>();
  readonly mes = input.required<string>();

  protected readonly pen = formatPen;
  protected readonly day = dayLabel;
  protected readonly reasons = REASONS;
  protected readonly reasonLabels = REASON_LABELS;
  protected readonly pageSize = PAGE_SIZE;
  protected readonly creditColumns = ['pick', 'date', 'description', 'amount'];
  protected readonly receivableColumns = ['document', 'customer', 'due', 'available', 'add'];

  protected readonly title = computed(() => monthLabel(this.mes()));
  protected readonly credits = signal<CreditPageView | null>(null);
  protected readonly pageIndex = signal(0);
  protected readonly picked = signal<CreditView[]>([]);
  protected readonly found = signal<OpenReceivableView[] | null>(null);
  protected readonly applied = signal<Applied[]>([]);
  protected readonly saving = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly search = new FormGroup({
    query: new FormControl('', { nonNullable: true }),
  });
  protected readonly differenceReason = new FormControl<Reason | null>(null);
  protected readonly differenceNote = new FormControl('', { nonNullable: true });

  protected readonly length = computed(() =>
    keysetLength(this.pageIndex(), PAGE_SIZE, this.credits()?.has_next ?? false),
  );
  protected readonly creditsCents = computed(() =>
    this.picked().reduce((total, credit) => total + credit.amount_cents, 0),
  );
  protected readonly appliedCents = computed(() =>
    this.applied().reduce((total, item) => total + (parseSoles(item.amount) ?? 0), 0),
  );
  protected readonly differenceCents = computed(() => this.creditsCents() - this.appliedCents());
  protected readonly invalidAmounts = computed(() =>
    this.applied().some((item) => {
      const cents = parseSoles(item.amount);
      return cents === null || cents <= 0 || cents > item.receivable.available_cents;
    }),
  );
  protected readonly ready = computed(
    () =>
      this.picked().length > 0 &&
      this.applied().length > 0 &&
      !this.invalidAmounts() &&
      !this.saving(),
  );

  private get month(): Month {
    return { accountId: this.cuenta(), period: this.mes() };
  }

  async ngOnInit(): Promise<void> {
    await Promise.all([this.loadCredits({}), this.find()]);
  }

  protected isPicked(credit: CreditView): boolean {
    return this.picked().some((item) => item.id === credit.id);
  }

  protected toggle(credit: CreditView): void {
    this.picked.update((items) =>
      this.isPicked(credit) ? items.filter((item) => item.id !== credit.id) : [...items, credit],
    );
  }

  protected isApplied(receivable: OpenReceivableView): boolean {
    return this.applied().some((item) => item.receivable.id === receivable.id);
  }

  protected add(receivable: OpenReceivableView): void {
    if (!this.isApplied(receivable)) {
      const amount = solesInput(receivable.available_cents);
      this.applied.update((items) => [...items, { receivable, amount }]);
    }
  }

  protected remove(receivable: OpenReceivableView): void {
    this.applied.update((items) => items.filter((item) => item.receivable.id !== receivable.id));
  }

  protected setAmount(receivable: OpenReceivableView, amount: string): void {
    this.applied.update((items) =>
      items.map((item) => (item.receivable.id === receivable.id ? { ...item, amount } : item)),
    );
  }

  protected partial(item: Applied): boolean {
    const cents = parseSoles(item.amount);
    return cents !== null && cents > 0 && cents < item.receivable.available_cents;
  }

  protected async find(): Promise<void> {
    try {
      const page = await this.matching.openReceivables(
        this.search.controls.query.value.trim() || null,
        {},
      );
      this.found.set(page.receivables);
    } catch (error) {
      this.error.set(matchingErrorMessage(error));
    }
  }

  protected async turn(event: PageEvent): Promise<void> {
    const page = this.credits();
    if (!page) {
      return;
    }
    const forward = event.pageIndex > this.pageIndex();
    this.pageIndex.set(event.pageIndex);
    await this.loadCredits(
      forward ? { after: page.next_cursor } : { before: page.previous_cursor },
    );
  }

  protected async save(): Promise<void> {
    const difference = this.differenceCents();
    this.saving.set(true);
    this.error.set(null);
    try {
      await this.matching.createManual(this.month, {
        creditIds: this.picked().map((credit) => credit.id),
        applications: this.applied().map((item) => ({
          receivableId: item.receivable.id,
          appliedCents: parseSoles(item.amount) ?? 0,
        })),
        differenceReason: difference === 0 ? null : this.differenceReason.value,
        differenceNote: difference === 0 ? null : this.differenceNote.value.trim() || null,
      });
      await this.router.navigate(['/bandeja'], {
        queryParams: { cuenta: this.cuenta(), mes: this.mes() },
      });
    } catch (error) {
      this.error.set(matchingErrorMessage(error));
    } finally {
      this.saving.set(false);
    }
  }

  private async loadCredits(cursor: Cursor): Promise<void> {
    try {
      this.credits.set(await this.matching.credits(this.month, NO_FILTERS, cursor));
    } catch (error) {
      this.error.set(matchingErrorMessage(error));
    }
  }
}
