import { ImportFileView } from '../../api/models/import-file-view';
import { PreviewStatus } from './imports.service';

export type ImportKind = ImportFileView['kind'];

export interface PreviewTab {
  status: PreviewStatus;
  label: string;
}

export interface KindTexts {
  label: string;
  records: string;
  sameFile: string;
  tabs: readonly PreviewTab[];
  nothing: string;
  confirmed: string;
  voided: string;
  voidEffect: string;
}

export const STATUS_LABELS: Record<ImportFileView['status'], string> = {
  uploaded: 'Subido',
  parsing: 'Procesando',
  previewed: 'Por confirmar',
  failed: 'Con error',
  confirmed: 'Confirmado',
  discarded: 'Descartado',
  voided: 'Anulado',
};

export const KIND_TEXTS: Record<ImportKind, KindTexts> = {
  bank_statement: {
    label: 'Extracto',
    records: 'movimientos',
    sameFile: 'en esta cuenta',
    tabs: [
      { status: 'ok', label: 'Válidas' },
      { status: 'error', label: 'Con errores' },
      { status: 'duplicate', label: 'Ya importadas' },
      { status: 'closed_period', label: 'Período cerrado' },
    ],
    nothing: 'ningún movimiento',
    confirmed: 'Sus movimientos ya están disponibles para conciliar.',
    voided: 'Sus movimientos ya no cuentan.',
    voidEffect: 'Sus movimientos dejarán de contar y podrás volver a importar el archivo.',
  },
  receivables: {
    label: 'Cobros',
    records: 'cobros',
    sameFile: 'en esta organización',
    tabs: [
      { status: 'ok', label: 'Nuevos o con cambios' },
      { status: 'error', label: 'Con errores' },
      { status: 'duplicate', label: 'Sin cambios' },
      { status: 'conflict', label: 'En conflicto' },
    ],
    nothing: 'ningún cobro',
    confirmed: 'Sus cobros ya están disponibles para conciliar.',
    voided: 'Los cobros que creó quedaron anulados.',
    voidEffect:
      'Los cobros que creó quedarán anulados. Las actualizaciones de cobros que ya existían no se deshacen.',
  },
};
