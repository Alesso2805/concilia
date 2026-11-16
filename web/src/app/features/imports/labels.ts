import { ImportFileView } from '../../api/models/import-file-view';
import { PreviewStatus } from './imports.service';

export const STATUS_LABELS: Record<ImportFileView['status'], string> = {
  uploaded: 'Subido',
  parsing: 'Procesando',
  previewed: 'Por confirmar',
  failed: 'Con error',
  confirmed: 'Confirmado',
  discarded: 'Descartado',
  voided: 'Anulado',
};

export const TAB_LABELS: Record<PreviewStatus, string> = {
  ok: 'Válidas',
  error: 'Con errores',
  duplicate: 'Ya importadas',
  closed_period: 'Período cerrado',
};
