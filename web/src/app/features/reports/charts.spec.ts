import { barOptions, CHART_COLORS, describeRows, percent } from './charts';

describe('charts', () => {
  it('rounds shares down to a tenth of a percent', () => {
    expect(percent(0, 0)).toBe('—');
    expect(percent(2, 3)).toBe('66.6 %');
    expect(percent(999, 1000)).toBe('99.9 %');
    expect(percent(5, 5)).toBe('100.0 %');
  });

  it('describes every bar for assistive technology', () => {
    expect(
      describeRows([
        { label: 'Conciliados', count: 1, cents: 118_000 },
        { label: 'Sin conciliar', count: 2, cents: 50 },
      ]),
    ).toBe('Conciliados: S/ 1,180.00, 1 abono; Sin conciliar: S/ 0.50, 2 abonos');
  });

  it('builds an accessible bar chart in soles', () => {
    const options = barOptions(
      [{ label: '0 a 7 días', count: 3, cents: 12_345 }],
      'Pendientes',
      CHART_COLORS.dark,
    ) as {
      aria: { enabled: boolean; decal: { show: boolean }; label: { description: string } };
      color: string[];
      xAxis: { data: string[]; axisLabel: { color: string } };
      series: { data: number[] }[];
    };

    expect(options.color).toEqual(['#8bd6b4']);
    expect(options.xAxis.axisLabel.color).toBe('#e0e4d9');
    expect(options.aria.enabled).toBe(true);
    expect(options.aria.decal.show).toBe(true);
    expect(options.aria.label.description).toBe('Pendientes. 0 a 7 días: S/ 123.45, 3 abonos.');
    expect(options.xAxis.data).toEqual(['0 a 7 días']);
    expect(options.series[0].data).toEqual([123.45]);
  });
});
