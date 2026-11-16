import { DatePipe } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  OnInit,
  signal,
} from '@angular/core';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSelectModule } from '@angular/material/select';

import { MatchDetailView } from '../../api/models/match-detail-view';
import { formatPen } from '../../core/format/amounts';
import { SessionStore } from '../../core/session/session.store';
import {
  ACTION_LABELS,
  dayLabel,
  REASON_LABELS,
  RULE_LABELS,
  SOURCE_LABELS,
  STATUS_LABELS,
} from './labels';
import { Decision, MatchingService, matchingErrorMessage, Rule } from './matching.service';

type Reason = NonNullable<Decision['difference_reason']>;
type Action = Decision['action'];

const REASONS = Object.keys(REASON_LABELS) as Reason[];

@Component({
  selector: 'app-match-detail-dialog',
  imports: [
    DatePipe,
    ReactiveFormsModule,
    MatButtonModule,
    MatDialogModule,
    MatFormFieldModule,
    MatInputModule,
    MatProgressBarModule,
    MatSelectModule,
  ],
  templateUrl: './match-detail.dialog.html',
  styleUrl: './inbox.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MatchDetailDialog implements OnInit {
  private readonly matching = inject(MatchingService);
  private readonly session = inject(SessionStore);
  private readonly dialog = inject<MatDialogRef<MatchDetailDialog, boolean>>(MatDialogRef);
  private readonly matchId = inject<string>(MAT_DIALOG_DATA);

  protected readonly detail = signal<MatchDetailView | null>(null);
  protected readonly error = signal<string | null>(null);
  protected readonly deciding = signal(false);
  protected readonly pen = formatPen;
  protected readonly day = dayLabel;
  protected readonly reasons = REASONS;
  protected readonly reasonLabels = REASON_LABELS;
  protected readonly differenceReason = new FormControl<Reason | null>(null);
  protected readonly differenceNote = new FormControl('', { nonNullable: true });
  protected readonly reason = new FormControl('', { nonNullable: true });

  protected readonly analyst = computed(() => this.session.roles().has('analyst'));
  protected readonly reviewer = computed(() => this.session.roles().has('reviewer'));
  protected readonly canConfirm = computed(
    () => this.analyst() && this.detail()?.status === 'proposed',
  );
  protected readonly canApprove = computed(
    () => this.reviewer() && this.detail()?.status === 'confirmed',
  );
  protected readonly canRevert = computed(
    () => this.reviewer() && this.detail()?.status === 'approved',
  );

  async ngOnInit(): Promise<void> {
    try {
      const detail = await this.matching.detail(this.matchId);
      this.detail.set(detail);
      this.differenceReason.setValue((detail.suggested_difference_reason as Reason) ?? null);
    } catch (error) {
      this.error.set(matchingErrorMessage(error));
    }
  }

  protected origin(detail: MatchDetailView): string {
    const source = SOURCE_LABELS[detail.source] ?? detail.source;
    return detail.rule ? `${source}, ${RULE_LABELS[detail.rule as Rule]}` : source;
  }

  protected status(detail: MatchDetailView): string {
    return STATUS_LABELS[detail.status] ?? detail.status;
  }

  protected reasonLabel(code: string | null | undefined): string {
    return code ? (REASON_LABELS[code] ?? code) : '';
  }

  protected action(code: string): string {
    return ACTION_LABELS[code] ?? code;
  }

  protected async decide(action: Action): Promise<void> {
    const detail = this.detail();
    if (!detail) {
      return;
    }
    const decision: Decision = { action };
    if (action === 'confirm' && detail.difference_cents !== 0) {
      decision.difference_reason = this.differenceReason.value;
      decision.difference_note = this.differenceNote.value.trim() || null;
    }
    if (action === 'reject' || action === 'revert') {
      decision.reason = this.reason.value.trim() || null;
    }
    this.deciding.set(true);
    this.error.set(null);
    try {
      await this.matching.decide(detail.id, decision);
      this.dialog.close(true);
    } catch (error) {
      this.error.set(matchingErrorMessage(error));
    } finally {
      this.deciding.set(false);
    }
  }
}
