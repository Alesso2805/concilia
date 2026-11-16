const HUNDREDTHS = 100;
const SOLES = /^\d{1,7}(?:[.,]\d{1,2})?$/;
const PERCENT = /^\d{1,3}(?:[.,]\d{1,2})?$/;

function hundredths(text: string, pattern: RegExp): number | null {
  const value = text.trim();
  if (!pattern.test(value)) {
    return null;
  }
  const [whole, fraction = ''] = value.replace(',', '.').split('.');
  return Number(whole) * HUNDREDTHS + Number(fraction.padEnd(2, '0'));
}

function split(value: number): [number, number] {
  const rest = Math.abs(value) % HUNDREDTHS;
  return [(Math.abs(value) - rest) / HUNDREDTHS, rest];
}

/** Soles typed by a person (`1250.5`, `1250,50`) to integer cents, or null if malformed. */
export function parseSoles(text: string): number | null {
  return hundredths(text, SOLES);
}

/** A percentage typed by a person (`0.5`, `12`) to integer basis points, or null. */
export function parsePercent(text: string): number | null {
  return hundredths(text, PERCENT);
}

export function solesInput(cents: number): string {
  const [whole, rest] = split(cents);
  return `${cents < 0 ? '-' : ''}${whole}.${String(rest).padStart(2, '0')}`;
}

export function formatPen(cents: number): string {
  const [whole, rest] = split(cents);
  const grouped = whole.toLocaleString('en-US');
  return `S/ ${cents < 0 ? '-' : ''}${grouped}.${String(rest).padStart(2, '0')}`;
}

export function percentInput(basisPoints: number): string {
  const [whole, rest] = split(basisPoints);
  return rest ? `${whole}.${String(rest).padStart(2, '0').replace(/0$/, '')}` : String(whole);
}
