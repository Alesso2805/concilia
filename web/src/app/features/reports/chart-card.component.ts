import { DOCUMENT } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { NgxEchartsDirective, provideEchartsCore } from 'ngx-echarts';

import { formatPen } from '../../core/format/amounts';
import { barOptions, ChartRow, describeRows } from './charts';
import { echarts } from './echarts';

@Component({
  selector: 'app-chart-card',
  imports: [MatButtonModule, NgxEchartsDirective],
  providers: [provideEchartsCore({ echarts })],
  template: `
    <section class="chart" [attr.aria-labelledby]="headingId">
      <div class="chart__header">
        <h2 class="chart__title" [id]="headingId">{{ heading() }}</h2>
        @if (rows().length > 0) {
          <button
            mat-button
            type="button"
            [attr.aria-pressed]="asTable()"
            (click)="asTable.set(!asTable())"
          >
            {{ asTable() ? 'Ver como gráfico' : 'Ver como tabla' }}
          </button>
        }
      </div>
      @if (rows().length === 0) {
        <p class="chart__empty">{{ empty() }}</p>
      } @else if (asTable()) {
        <table class="chart__table">
          <caption class="cdk-visually-hidden">
            {{
              heading()
            }}
          </caption>
          <thead>
            <tr>
              <th scope="col">{{ category() }}</th>
              <th scope="col" class="chart__number">Abonos</th>
              <th scope="col" class="chart__number">Monto</th>
            </tr>
          </thead>
          <tbody>
            @for (row of rows(); track row.label) {
              <tr>
                <th scope="row">{{ row.label }}</th>
                <td class="chart__number">{{ row.count }}</td>
                <td class="chart__number">{{ pen(row.cents) }}</td>
              </tr>
            }
          </tbody>
        </table>
      } @else {
        <div
          class="chart__canvas"
          echarts
          role="img"
          [attr.aria-label]="summary()"
          [options]="options()"
          [initOpts]="{ renderer: 'svg' }"
        ></div>
      }
    </section>
  `,
  styleUrl: './reports.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ChartCard {
  private static next = 0;
  private readonly document = inject(DOCUMENT);

  readonly heading = input.required<string>();
  readonly category = input.required<string>();
  readonly rows = input.required<readonly ChartRow[]>();
  readonly empty = input('No hay datos para este mes.');

  protected readonly headingId = `chart-${ChartCard.next++}`;
  protected readonly asTable = signal(false);
  protected readonly pen = formatPen;
  protected readonly summary = computed(() => `${this.heading()}. ${describeRows(this.rows())}.`);
  protected readonly options = computed(() =>
    barOptions(this.rows(), this.heading(), this.textColor()),
  );

  private textColor(): string {
    const style = this.document.defaultView?.getComputedStyle(this.document.documentElement);
    return style?.getPropertyValue('--mat-sys-on-surface').trim() || '#1b1b1f';
  }
}
