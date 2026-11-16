import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, inject, OnInit, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MAT_DIALOG_DATA, MatDialogModule } from '@angular/material/dialog';
import { MatProgressBarModule } from '@angular/material/progress-bar';

import { MatchDetailView } from '../../api/models/match-detail-view';
import { formatPen } from '../../core/format/amounts';
import {
  ACTION_LABELS,
  dayLabel,
  REASON_LABELS,
  RULE_LABELS,
  SOURCE_LABELS,
  STATUS_LABELS,
} from './labels';
import { MatchingService, matchingErrorMessage, Rule } from './matching.service';

@Component({
  selector: 'app-match-detail-dialog',
  imports: [DatePipe, MatButtonModule, MatDialogModule, MatProgressBarModule],
  templateUrl: './match-detail.dialog.html',
  styleUrl: './inbox.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MatchDetailDialog implements OnInit {
  private readonly matching = inject(MatchingService);
  private readonly matchId = inject<string>(MAT_DIALOG_DATA);

  protected readonly detail = signal<MatchDetailView | null>(null);
  protected readonly error = signal<string | null>(null);
  protected readonly pen = formatPen;
  protected readonly day = dayLabel;

  async ngOnInit(): Promise<void> {
    try {
      this.detail.set(await this.matching.detail(this.matchId));
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

  protected reason(code: string | null | undefined): string {
    return code ? (REASON_LABELS[code] ?? code) : '';
  }

  protected action(code: string): string {
    return ACTION_LABELS[code] ?? code;
  }
}
