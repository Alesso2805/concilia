import { formatPen, parsePercent, parseSoles, percentInput, solesInput } from './amounts';

describe('amounts', () => {
  it.each([
    ['1', 100],
    ['1.5', 150],
    ['1,05', 105],
    [' 1250.50 ', 125_050],
    ['0.01', 1],
    ['9999999.99', 999_999_999],
  ])('reads %s soles as %i cents', (text, cents) => {
    expect(parseSoles(text)).toBe(cents);
  });

  it.each(['', '1.234', '-1', '1e3', '1.000,00', 'abc', '10000000'])('rejects %j', (text) => {
    expect(parseSoles(text)).toBeNull();
  });

  it('round-trips every cent value without floating point drift', () => {
    for (let cents = 0; cents <= 100_000; cents += 7) {
      expect(parseSoles(solesInput(cents))).toBe(cents);
    }
  });

  it('formats soles for reading', () => {
    expect(formatPen(123_456_789)).toBe('S/ 1,234,567.89');
    expect(formatPen(-50)).toBe('S/ -0.50');
  });

  it.each([
    ['0.5', 50],
    ['12', 1200],
    ['12,25', 1225],
  ])('reads %s %% as %i basis points', (text, bp) => {
    expect(parsePercent(text)).toBe(bp);
    expect(parsePercent(percentInput(bp))).toBe(bp);
  });

  it('writes percentages without trailing zeros', () => {
    expect([percentInput(1000), percentInput(50), percentInput(1205)]).toEqual([
      '10',
      '0.5',
      '12.05',
    ]);
  });
});
