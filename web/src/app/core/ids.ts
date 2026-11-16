import { v7 } from 'uuid';

// Client-generated ids for idempotent POSTs (ADR-0009): uuid v7, close to server time.
export function newId(): string {
  return v7();
}
