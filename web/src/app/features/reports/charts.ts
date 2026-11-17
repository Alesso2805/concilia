import type { EChartsCoreOption } from 'echarts/core';

import { formatPen } from '../../core/format/amounts';
import { ColorScheme } from '../../core/theme/theme.service';

export interface ChartRow {
  label: string;
  count: number;
  cents: number;
}

/**
 * Share of `part` in `total` rounded down to a tenth of a percent, so a month shows 100 % only
 * when everything is reconciled.
 */
export function percent(part: number, total: number): string {
  if (total <= 0) {
    return '—';
  }
  const tenths = Math.floor((part * 1000) / total);
  return `${Math.floor(tenths / 10)}.${tenths % 10} %`;
}

function quantity(count: number): string {
  return count === 1 ? '1 abono' : `${count} abonos`;
}

export function describeRows(rows: readonly ChartRow[]): string {
  return rows
    .map((row) => `${row.label}: ${formatPen(row.cents)}, ${quantity(row.count)}`)
    .join('; ');
}

const SOLES = new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 });

export interface ChartColors {
  text: string;
  bar: string;
}

/**
 * ECharts draws SVG attributes, which cannot read the theme's CSS variables, so these repeat
 * `--mat-sys-on-surface` and `--mat-sys-primary` from `_theme-colors.scss` (ADR-0011).
 */
export const CHART_COLORS: Record<ColorScheme, ChartColors> = {
  light: { text: '#191d16', bar: '#1c6b50' },
  dark: { text: '#e0e4d9', bar: '#8bd6b4' },
};

export function barOptions(
  rows: readonly ChartRow[],
  title: string,
  colors: ChartColors,
): EChartsCoreOption {
  return {
    animation: false,
    aria: {
      enabled: true,
      label: { description: `${title}. ${describeRows(rows)}.` },
      decal: { show: true },
    },
    textStyle: { fontFamily: 'Inter, sans-serif' },
    grid: { left: 8, right: 16, top: 16, bottom: 8, containLabel: true },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      valueFormatter: (value: number) => formatPen(Math.round(value * 100)),
    },
    color: [colors.bar],
    xAxis: {
      type: 'category',
      data: rows.map((row) => row.label),
      axisLabel: { color: colors.text, interval: 0, width: 80, overflow: 'break' },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: colors.text, formatter: (value: number) => `S/ ${SOLES.format(value)}` },
    },
    series: [{ type: 'bar', name: 'Monto', data: rows.map((row) => row.cents / 100) }],
  };
}
