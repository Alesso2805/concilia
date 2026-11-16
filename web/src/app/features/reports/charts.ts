import type { EChartsCoreOption } from 'echarts/core';

import { formatPen } from '../../core/format/amounts';

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

export function barOptions(
  rows: readonly ChartRow[],
  title: string,
  textColor: string,
): EChartsCoreOption {
  return {
    animation: false,
    aria: {
      enabled: true,
      label: { description: `${title}. ${describeRows(rows)}.` },
      decal: { show: true },
    },
    grid: { left: 8, right: 16, top: 16, bottom: 8, containLabel: true },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      valueFormatter: (value: number) => formatPen(Math.round(value * 100)),
    },
    xAxis: {
      type: 'category',
      data: rows.map((row) => row.label),
      axisLabel: { color: textColor, interval: 0 },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: textColor, formatter: (value: number) => `S/ ${value}` },
    },
    series: [{ type: 'bar', name: 'Monto', data: rows.map((row) => row.cents / 100) }],
  };
}
