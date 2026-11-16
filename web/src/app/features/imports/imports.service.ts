import { HttpErrorResponse } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { Api } from '../../api/api';
import {
  confirmImport,
  discardImport,
  getImport,
  listImportRows,
  listImports,
  uploadImport,
  voidImport,
} from '../../api/functions';
import { FilePageView } from '../../api/models/file-page-view';
import { ImportSummaryView } from '../../api/models/import-summary-view';
import { RowPageView } from '../../api/models/row-page-view';
import { UploadView } from '../../api/models/upload-view';
import { newId } from '../../core/ids';

export type PreviewStatus = 'ok' | 'error' | 'duplicate' | 'closed_period' | 'conflict';

const FILE_MESSAGES: Record<string, string> = {
  abandoned: 'El procesamiento no terminó. Vuelve a subir el archivo.',
  empty_file: 'El archivo está vacío.',
  file_too_large: 'El archivo supera los 5 MB.',
  missing_columns:
    'Faltan columnas del perfil en el encabezado. Revisa los nombres y las filas a saltar del perfil.',
  missing_header: 'El archivo no tiene la fila de encabezados donde el perfil la espera.',
  missing_sheet: 'No encontramos en el archivo la hoja que indica el perfil.',
  no_rows: 'El archivo no tiene filas con datos.',
  too_many_rows: 'El archivo supera las 10 000 filas.',
  unreadable_file: 'No pudimos leer el archivo. Sube un CSV o un Excel (.xlsx) válido.',
  wrong_encoding: 'El texto del archivo no está en la codificación del perfil.',
  wrong_format: 'El archivo no coincide con el formato del perfil (CSV o Excel).',
};

const ACTION_MESSAGES: Record<string, string> = {
  active_matches: 'No se puede anular: hay movimientos o cobros en conciliaciones en curso.',
  closed_period: 'No se puede anular: hay movimientos en un período cerrado.',
  duplicate_file: 'Ya confirmaste un archivo idéntico.',
  not_found: 'Esta importación ya no existe.',
  wrong_state: 'La importación cambió de estado. Actualiza la página.',
};

export const ROW_MESSAGES: Record<string, string> = {
  customer_too_long: 'Nombre del cliente demasiado largo',
  description_too_long: 'Descripción demasiado larga',
  due_before_issue: 'Vence antes de su emisión',
  formula_not_allowed: 'Celda con fórmula',
  invalid_amount: 'Monto no válido',
  invalid_date: 'Fecha no válida',
  invalid_document: 'Número de documento no válido (por ejemplo, F001-123)',
  invalid_tax_id: 'RUC o DNI no válido',
  missing_amount: 'Falta el monto',
  missing_customer: 'Falta el cliente',
  missing_date: 'Falta la fecha',
  missing_description: 'Falta la descripción',
  missing_document: 'Falta el número de documento',
  non_positive_amount: 'El monto debe ser mayor que cero',
  repeated_document: 'Documento repetido en el archivo',
  too_many_decimals: 'Monto con más de 2 decimales',
  zero_amount: 'Monto cero',
};

export function fileErrorMessage(code: string | null | undefined): string {
  return (code && FILE_MESSAGES[code]) || 'No pudimos procesar el archivo.';
}

export function codeMessage(code: string | null | undefined): string {
  return (
    (code && (FILE_MESSAGES[code] ?? ACTION_MESSAGES[code])) ||
    'No pudimos completar la operación. Intenta de nuevo.'
  );
}

export function importErrorMessage(error: unknown): string {
  const detail = error instanceof HttpErrorResponse ? (error.error?.detail as string) : '';
  return (
    FILE_MESSAGES[detail] ??
    ACTION_MESSAGES[detail] ??
    'No pudimos completar la operación. Intenta de nuevo.'
  );
}

@Injectable({ providedIn: 'root' })
export class ImportsService {
  private readonly api = inject(Api);

  list(cursor: { after?: string | null; before?: string | null } = {}): Promise<FilePageView> {
    return firstValueFrom(this.api.invoke(listImports, { limit: 10, ...cursor }));
  }

  upload(profileId: string, file: File): Promise<UploadView> {
    return firstValueFrom(
      this.api.invoke(uploadImport, {
        body: { id: newId(), import_profile_id: profileId, file: file as unknown as string },
      }),
    );
  }

  summary(fileId: string): Promise<ImportSummaryView> {
    return firstValueFrom(this.api.invoke(getImport, { file_id: fileId }));
  }

  rows(
    fileId: string,
    status: PreviewStatus,
    cursor: { after?: number | null; before?: number | null },
  ): Promise<RowPageView> {
    return firstValueFrom(
      this.api.invoke(listImportRows, { file_id: fileId, status, limit: 25, ...cursor }),
    );
  }

  discard(fileId: string): Promise<void> {
    return firstValueFrom(this.api.invoke(discardImport, { file_id: fileId }));
  }

  async confirm(fileId: string): Promise<string> {
    return (await firstValueFrom(this.api.invoke(confirmImport, { file_id: fileId }))).job_id;
  }

  void(fileId: string, reason: string): Promise<void> {
    return firstValueFrom(this.api.invoke(voidImport, { file_id: fileId, body: { reason } }));
  }
}
