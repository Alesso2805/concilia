import { InboxTab, Rule } from './matching.service';

export const TABS: readonly { tab: InboxTab; label: string }[] = [
  { tab: 'free', label: 'Libres' },
  { tab: 'proposed', label: 'Propuestas' },
  { tab: 'confirmed', label: 'Confirmadas' },
  { tab: 'approved', label: 'Aprobadas' },
];

export const EMPTY_TABS: Record<InboxTab, { title: string; hint: string }> = {
  free: {
    title: 'No hay abonos libres',
    hint: 'Todos los abonos de este mes están en alguna coincidencia.',
  },
  proposed: {
    title: 'No hay propuestas',
    hint: 'Usa «Correr el motor» para que busque coincidencias en este mes, o concilia a mano.',
  },
  confirmed: {
    title: 'No hay coincidencias confirmadas',
    hint: 'Aparecen aquí cuando alguien confirma una propuesta.',
  },
  approved: {
    title: 'No hay coincidencias aprobadas',
    hint: 'Aparecen aquí cuando otra persona aprueba una coincidencia confirmada.',
  },
};

export const FILTERED_HINT = 'Ninguna cumple los filtros. Prueba quitándolos.';

export const RULE_LABELS: Record<Rule, string> = {
  R1: 'R1 · Exacta',
  R2: 'R2 · Varios documentos',
  R3: 'R3 · Referencia con diferencia',
  R4: 'R4 · Mismo cliente, varios cobros',
  R5: 'R5 · Cobro pagado en partes',
  R6: 'R6 · Monto y fecha',
};

export const RULE_NAMES: Record<Rule, string> = {
  R1: 'R1 · Exacta',
  R2: 'R2 · Varios documentos',
  R3: 'R3 · Con diferencia',
  R4: 'R4 · Mismo cliente',
  R5: 'R5 · Pago en partes',
  R6: 'R6 · Monto y fecha',
};

export const SOURCE_LABELS: Record<string, string> = {
  engine: 'Motor',
  ai: 'Asistente de IA',
  manual: 'Manual',
};

export const STATUS_LABELS: Record<string, string> = {
  proposed: 'Propuesta',
  confirmed: 'Confirmada',
  approved: 'Aprobada',
  discarded: 'Descartada',
  rejected: 'Rechazada',
  reverted: 'Revertida',
};

export const ACTION_LABELS: Record<string, string> = {
  confirm: 'Confirmó',
  discard: 'Descartó',
  approve: 'Aprobó',
  reject: 'Rechazó',
  revert: 'Revirtió',
};

export const REASON_LABELS: Record<string, string> = {
  commission: 'Comisión',
  detraction: 'Detracción',
  rounding: 'Redondeo',
  overpayment: 'Sobrepago',
  other: 'Otro',
};

const MONTHS = [
  'enero',
  'febrero',
  'marzo',
  'abril',
  'mayo',
  'junio',
  'julio',
  'agosto',
  'septiembre',
  'octubre',
  'noviembre',
  'diciembre',
];

/** `2027-01-01` to `enero de 2027`, without time zones getting in the way. */
export function monthLabel(period: string): string {
  const [year, month] = period.split('-').map(Number);
  return `${MONTHS[month - 1]} de ${year}`;
}

export function dayLabel(isoDate: string): string {
  return isoDate.split('-').reverse().join('/');
}
