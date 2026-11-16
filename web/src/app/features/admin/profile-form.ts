import {
  AbstractControl,
  FormControl,
  FormGroup,
  NonNullableFormBuilder,
  ValidationErrors,
  Validators,
} from '@angular/forms';

import { DateFormat } from '../../api/models/date-format';
import { FileFormat } from '../../api/models/file-format';
import { ReceivablesConfig } from '../../api/models/receivables-config';
import { StatementConfig } from '../../api/models/statement-config';
import { ProfileDraft } from './banking.service';

export type ProfileKind = 'bank_statement' | 'receivables';
export type AmountLayout = 'signed' | 'split';
type Delimiter = NonNullable<StatementConfig['delimiter']>;
type DecimalSeparator = NonNullable<StatementConfig['decimal_separator']>;
type ThousandsSeparator = NonNullable<StatementConfig['thousands_separator']>;
type Encoding = NonNullable<StatementConfig['encoding']>;

export const KIND_LABELS: Record<ProfileKind, string> = {
  bank_statement: 'Extracto bancario',
  receivables: 'Cobros esperados',
};
export const DATE_FORMATS: readonly DateFormat[] = [
  'DD/MM/YYYY',
  'DD-MM-YYYY',
  'DD/MM/YY',
  'YYYY-MM-DD',
];
export const DELIMITERS: readonly { value: Delimiter; label: string }[] = [
  { value: ',', label: 'Coma (,)' },
  { value: ';', label: 'Punto y coma (;)' },
  { value: '\t', label: 'Tabulador' },
  { value: '|', label: 'Barra vertical (|)' },
];
export const DECIMAL_SEPARATORS: readonly { value: DecimalSeparator; label: string }[] = [
  { value: '.', label: 'Punto (1234.56)' },
  { value: ',', label: 'Coma (1234,56)' },
];
export const THOUSANDS_SEPARATORS: readonly { value: ThousandsSeparator; label: string }[] = [
  { value: '', label: 'Ninguno' },
  { value: ',', label: 'Coma (1,234)' },
  { value: '.', label: 'Punto (1.234)' },
  { value: ' ', label: 'Espacio (1 234)' },
];
export const STATEMENT_COLUMNS = [
  { key: 'date', label: 'Fecha' },
  { key: 'description', label: 'Descripción' },
  { key: 'operation_number', label: 'Número de operación (opcional)' },
  { key: 'amount', label: 'Monto con signo' },
  { key: 'debit', label: 'Cargo' },
  { key: 'credit', label: 'Abono' },
] as const;
export const RECEIVABLES_COLUMNS = [
  { key: 'customer_name', label: 'Cliente' },
  { key: 'customer_tax_id', label: 'RUC (opcional)' },
  { key: 'doc_number', label: 'Número de documento' },
  { key: 'issued_on', label: 'Emisión' },
  { key: 'due_on', label: 'Vencimiento' },
  { key: 'amount', label: 'Monto' },
] as const;

const OPTIONAL_COLUMNS = new Set(['operation_number', 'customer_tax_id']);

function separatorsDiffer(group: AbstractControl): ValidationErrors | null {
  const { decimal_separator, thousands_separator } = group.value as Record<string, string>;
  return decimal_separator === thousands_separator ? { separators: true } : null;
}

function distinctColumns(group: AbstractControl): ValidationErrors | null {
  const names = Object.values((group as FormGroup).controls)
    .filter((control) => control.enabled)
    .map((control) => String(control.value).trim().toLocaleLowerCase('es'))
    .filter(Boolean);
  return new Set(names).size === names.length ? null : { duplicated: true };
}

function columnsGroup<K extends string>(
  fb: NonNullableFormBuilder,
  keys: readonly K[],
): FormGroup<Record<K, FormControl<string>>> {
  const controls = Object.fromEntries(
    keys.map((key) => [
      key,
      fb.control(
        '',
        OPTIONAL_COLUMNS.has(key)
          ? [Validators.maxLength(80)]
          : [Validators.required, Validators.maxLength(80)],
      ),
    ]),
  ) as Record<K, FormControl<string>>;
  return new FormGroup(controls, { validators: distinctColumns });
}

export function profileForm(fb: NonNullableFormBuilder) {
  return fb.group(
    {
      kind: fb.control<ProfileKind>('bank_statement'),
      bank_account_id: fb.control('', Validators.required),
      name: fb.control('', [Validators.required, Validators.maxLength(80)]),
      format: fb.control<FileFormat>('xlsx'),
      sheet: fb.control('', Validators.maxLength(31)),
      encoding: fb.control<Encoding>('utf-8'),
      delimiter: fb.control<Delimiter>(','),
      skip_rows: fb.control(0, [Validators.required, Validators.min(0), Validators.max(50)]),
      date_format: fb.control<DateFormat>('DD/MM/YYYY'),
      decimal_separator: fb.control<DecimalSeparator>('.'),
      thousands_separator: fb.control<ThousandsSeparator>(''),
      amount_layout: fb.control<AmountLayout>('signed'),
      statement: columnsGroup(
        fb,
        STATEMENT_COLUMNS.map((column) => column.key),
      ),
      receivables: columnsGroup(
        fb,
        RECEIVABLES_COLUMNS.map((column) => column.key),
      ),
    },
    { validators: separatorsDiffer },
  );
}

export type ProfileForm = ReturnType<typeof profileForm>;

function toggle(control: AbstractControl, enabled: boolean): void {
  if (enabled && control.disabled) {
    control.enable({ emitEvent: false });
  } else if (!enabled && control.enabled) {
    control.disable({ emitEvent: false });
  }
}

/** Enables only the controls that apply to the chosen kind, file format and amount layout. */
export function syncProfileForm(form: ProfileForm): void {
  const { kind, format, amount_layout } = form.getRawValue();
  const statement = kind === 'bank_statement';
  toggle(form.controls.bank_account_id, statement);
  toggle(form.controls.statement, statement);
  toggle(form.controls.receivables, !statement);
  toggle(form.controls.amount_layout, statement);
  toggle(form.controls.sheet, format === 'xlsx');
  toggle(form.controls.delimiter, format === 'csv');
  toggle(form.controls.encoding, format === 'csv');
  const columns = form.controls.statement.controls;
  toggle(columns.amount, statement && amount_layout === 'signed');
  toggle(columns.debit, statement && amount_layout === 'split');
  toggle(columns.credit, statement && amount_layout === 'split');
  form.updateValueAndValidity({ emitEvent: false });
}

export function applyConfig(
  form: ProfileForm,
  kind: ProfileKind,
  config: StatementConfig | ReceivablesConfig,
): void {
  form.patchValue({
    kind,
    format: config.format,
    sheet: config.sheet ?? '',
    encoding: config.encoding ?? 'utf-8',
    delimiter: config.delimiter ?? ',',
    skip_rows: config.skip_rows ?? 0,
    date_format: config.date_format,
    decimal_separator: config.decimal_separator ?? '.',
    thousands_separator: config.thousands_separator ?? '',
  });
  if (kind === 'bank_statement') {
    const columns = (config as StatementConfig).columns;
    form.controls.amount_layout.setValue(columns.amount ? 'signed' : 'split');
    form.controls.statement.patchValue({
      date: columns.date,
      description: columns.description,
      operation_number: columns.operation_number ?? '',
      amount: columns.amount ?? '',
      debit: columns.debit ?? '',
      credit: columns.credit ?? '',
    });
  } else {
    const columns = (config as ReceivablesConfig).columns;
    form.controls.receivables.patchValue({
      ...columns,
      customer_tax_id: columns.customer_tax_id ?? '',
    });
  }
  syncProfileForm(form);
}

function optional(value: string): string | null {
  return value.trim() ? value.trim() : null;
}

export function toDraft(form: ProfileForm): ProfileDraft {
  const value = form.getRawValue();
  const csv = value.format === 'csv';
  const layout = {
    format: value.format,
    sheet: csv ? null : optional(value.sheet),
    encoding: value.encoding,
    delimiter: value.delimiter,
    skip_rows: value.skip_rows,
    date_format: value.date_format,
    decimal_separator: value.decimal_separator,
    thousands_separator: value.thousands_separator,
  };
  if (value.kind === 'receivables') {
    const columns = value.receivables;
    return {
      kind: 'receivables',
      name: value.name.trim(),
      config: {
        ...layout,
        columns: { ...columns, customer_tax_id: optional(columns.customer_tax_id) },
      },
    };
  }
  const columns = value.statement;
  const signed = value.amount_layout === 'signed';
  return {
    kind: 'bank_statement',
    name: value.name.trim(),
    bank_account_id: value.bank_account_id,
    config: {
      ...layout,
      columns: {
        date: columns.date.trim(),
        description: columns.description.trim(),
        operation_number: optional(columns.operation_number),
        amount: signed ? columns.amount.trim() : null,
        debit: signed ? null : columns.debit.trim(),
        credit: signed ? null : columns.credit.trim(),
      },
    },
  };
}
