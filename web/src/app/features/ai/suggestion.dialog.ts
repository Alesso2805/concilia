import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  inject,
  OnInit,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, ReactiveFormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';

import { CreditView } from '../../api/models/credit-view';
import { SuggestionItemView } from '../../api/models/suggestion-item-view';
import { SuggestionView } from '../../api/models/suggestion-view';
import { UsageView } from '../../api/models/usage-view';
import { formatPen } from '../../core/format/amounts';
import { isFinished, JobTracker } from '../../core/jobs/job-tracker';
import { dayLabel, REASON_LABELS } from '../matching/labels';
import { aiCodeMessage, aiErrorMessage, AiService } from './ai.service';

export interface SuggestionDialogData {
  credit: CreditView;
  usage: UsageView;
}

const CONFIDENCE_LABELS: Record<string, string> = {
  high: 'confianza alta',
  medium: 'confianza media',
  low: 'confianza baja',
};

@Component({
  selector: 'app-suggestion-dialog',
  imports: [
    ReactiveFormsModule,
    MatButtonModule,
    MatDialogModule,
    MatFormFieldModule,
    MatInputModule,
    MatProgressBarModule,
  ],
  templateUrl: './suggestion.dialog.html',
  styleUrl: './ai.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SuggestionDialog implements OnInit {
  private readonly ai = inject(AiService);
  private readonly jobs = inject(JobTracker);
  private readonly dialog = inject<MatDialogRef<SuggestionDialog, boolean>>(MatDialogRef);
  private readonly destroyRef = inject(DestroyRef);
  protected readonly data = inject<SuggestionDialogData>(MAT_DIALOG_DATA);

  protected readonly pen = formatPen;
  protected readonly day = dayLabel;
  protected readonly view = signal<SuggestionView | null>(null);
  protected readonly waiting = signal(true);
  protected readonly error = signal<string | null>(null);
  protected readonly deciding = signal(false);
  protected readonly rejecting = signal<number | null>(null);
  protected readonly reason = new FormControl('', { nonNullable: true });

  async ngOnInit(): Promise<void> {
    try {
      const requested = await this.ai.ask(this.data.credit.id);
      this.follow(requested.job_id, requested.id);
    } catch (error) {
      this.waiting.set(false);
      this.error.set(aiErrorMessage(error));
    }
  }

  protected heading(item: SuggestionItemView): string {
    return `Sugerencia ${item.index + 1}, ${CONFIDENCE_LABELS[item.confidence] ?? item.confidence}`;
  }

  protected reasonLabel(code: string | null | undefined): string {
    return code ? (REASON_LABELS[code] ?? code) : '';
  }

  protected startRejecting(index: number): void {
    this.reason.reset();
    this.rejecting.set(index);
  }

  protected async decide(item: SuggestionItemView, action: 'accept' | 'reject'): Promise<void> {
    const view = this.view();
    if (!view) {
      return;
    }
    const reason = action === 'reject' ? this.reason.value.trim() : null;
    if (action === 'reject' && !reason) {
      this.error.set(aiCodeMessage('reason_required'));
      return;
    }
    this.deciding.set(true);
    this.error.set(null);
    try {
      await this.ai.decide(view.id, item.index, action, reason);
      if (action === 'accept') {
        this.dialog.close(true);
        return;
      }
      this.rejecting.set(null);
      this.view.set(await this.ai.suggestion(view.id));
    } catch (error) {
      this.error.set(aiErrorMessage(error));
    } finally {
      this.deciding.set(false);
    }
  }

  private follow(jobId: string, suggestionId: string): void {
    let finished = false;
    this.jobs
      .track(jobId)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (job) => {
          finished = isFinished(job);
          if (job.status === 'failed') {
            this.error.set(aiCodeMessage(job.error_code));
          }
        },
        error: (error: unknown) => {
          this.waiting.set(false);
          this.error.set(aiErrorMessage(error));
        },
        complete: () => {
          if (!finished) {
            this.waiting.set(false);
            this.error.set('La IA está tardando más de lo normal. Vuelve a intentarlo luego.');
            return;
          }
          void this.load(suggestionId);
        },
      });
  }

  private async load(suggestionId: string): Promise<void> {
    try {
      const view = await this.ai.suggestion(suggestionId);
      if (view.status === 'done') {
        this.view.set(view);
      }
    } catch (error) {
      this.error.set(aiErrorMessage(error));
    } finally {
      this.waiting.set(false);
    }
  }
}
