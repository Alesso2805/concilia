import { Injectable } from '@angular/core';
import { MatPaginatorIntl } from '@angular/material/paginator';

/** Labels for server keyset pages: previous and next only, with no total. */
@Injectable()
export class KeysetPaginatorIntl extends MatPaginatorIntl {
  override itemsPerPageLabel = 'Filas por página';
  override nextPageLabel = 'Página siguiente';
  override previousPageLabel = 'Página anterior';
  override firstPageLabel = 'Primera página';
  override lastPageLabel = 'Última página';
  override getRangeLabel = (page: number) => `Página ${page + 1}`;
}

/** The paginator length that enables "next" exactly when the server says there is more. */
export function keysetLength(pageIndex: number, pageSize: number, hasNext: boolean): number {
  return (pageIndex + 1) * pageSize + (hasNext ? 1 : 0);
}
