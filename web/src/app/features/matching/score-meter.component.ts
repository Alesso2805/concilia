import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

const BARS = 5;

/** How many of the five bars a score lights: one per 20 points, rounded. */
export function litBars(score: number): number {
  return Math.min(BARS, Math.max(0, Math.round(score / 20)));
}

@Component({
  selector: 'app-score-meter',
  template: `
    <span class="app-amount">{{ score() }}</span>
    <span class="meter" aria-hidden="true">
      @for (lit of bars(); track $index) {
        <span class="meter__bar" [class.meter__bar--lit]="lit"></span>
      }
    </span>
  `,
  styles: `
    :host {
      display: inline-flex;
      gap: 8px;
      align-items: center;
    }

    .meter {
      display: inline-flex;
      gap: 2px;
    }

    .meter__bar {
      width: 5px;
      height: 12px;
      border-radius: 2px;
      background: var(--mat-sys-outline-variant);
    }

    .meter__bar--lit {
      background: var(--mat-sys-primary);
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ScoreMeter {
  readonly score = input.required<number>();

  protected readonly bars = computed(() => {
    const lit = litBars(this.score());
    return Array.from({ length: BARS }, (_, index) => index < lit);
  });
}
