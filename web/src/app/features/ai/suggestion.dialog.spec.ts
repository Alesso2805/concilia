import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { of } from 'rxjs';

import { SuggestionView } from '../../api/models/suggestion-view';
import { JobTracker } from '../../core/jobs/job-tracker';
import { provideLocale } from '../../core/locale';
import { AiService } from './ai.service';
import { SuggestionDialog } from './suggestion.dialog';

const VIEW: SuggestionView = {
  id: 's1',
  job_id: 's1',
  bank_movement_id: 'c1',
  status: 'done',
  error_code: null,
  valid: true,
  no_match_reason: null,
  suggestions: [
    {
      index: 0,
      decision: null,
      receivables: [
        {
          alias: 'C1',
          receivable_id: 'r1',
          doc_number: 'F001-124',
          customer_name: 'Gloria SA',
          applied_cents: 49_000,
        },
      ],
      difference_cents: 1_000,
      difference_reason: 'commission',
      confidence: 'high',
      explanation: 'La descripción menciona a Gloria y el monto es cercano.',
      recomputed: true,
    },
  ],
};
const CREDIT = {
  id: 'c1',
  booked_on: '2027-02-07',
  description: 'TRANSF GLORIA',
  operation_number: null,
  amount_cents: 50_000,
};

async function settle(fixture: ComponentFixture<unknown>): Promise<void> {
  for (let round = 0; round < 3; round++) {
    await fixture.whenStable();
    await new Promise((resolve) => setTimeout(resolve));
  }
}

function text(fixture: ComponentFixture<unknown>): string {
  return ((fixture.nativeElement as HTMLElement).textContent ?? '').replace(/\s+/g, ' ');
}

function button(element: HTMLElement, label: string): HTMLButtonElement {
  return [...element.querySelectorAll('button')].find(
    (candidate) => candidate.textContent?.trim() === label,
  )!;
}

describe('SuggestionDialog', () => {
  let fixture: ComponentFixture<SuggestionDialog>;
  let ai: Record<string, ReturnType<typeof vi.fn>>;
  let close: ReturnType<typeof vi.fn>;

  async function render(
    job: object = { id: 's1', status: 'done', progress: 100, error_code: null },
    usage: object = { available: true, used_today: 2, daily_limit: 50 },
  ): Promise<HTMLElement> {
    ai = {
      ask: vi.fn(() => Promise.resolve({ ...VIEW, status: 'queued', suggestions: [] })),
      suggestion: vi.fn(() => Promise.resolve(VIEW)),
      decide: vi.fn(() => Promise.resolve({})),
    };
    close = vi.fn();
    TestBed.configureTestingModule({
      imports: [SuggestionDialog],
      providers: [
        provideLocale(),
        { provide: AiService, useValue: ai },
        { provide: JobTracker, useValue: { track: () => of(job) } },
        { provide: MatDialogRef, useValue: { close } },
        { provide: MAT_DIALOG_DATA, useValue: { credit: CREDIT, usage } },
      ],
    });
    fixture = TestBed.createComponent(SuggestionDialog);
    await settle(fixture);
    return fixture.nativeElement as HTMLElement;
  }

  it('shows each suggestion with its confidence, explanation, amounts and difference', async () => {
    await render();

    expect(ai['ask']).toHaveBeenCalledWith('c1');
    expect(text(fixture)).toContain('Sugerencia 1, confianza alta');
    expect(text(fixture)).toContain('La descripción menciona a Gloria');
    expect(text(fixture)).toContain('F001-124');
    expect(text(fixture)).toContain('S/ 490.00');
    expect(text(fixture)).toContain('Diferencia: S/ 10.00 (motivo sugerido: Comisión)');
    expect(text(fixture)).toContain('El sistema recalculó los montos aplicados.');
    expect(text(fixture)).toContain('Consultas de hoy: 3 de 50.');
  });

  it('accepts a suggestion and closes so the inbox can refresh', async () => {
    const element = await render();

    button(element, 'Aceptar').click();
    await settle(fixture);

    expect(ai['decide']).toHaveBeenCalledWith('s1', 0, 'accept', null);
    expect(close).toHaveBeenCalledWith(true);
  });

  it('rejects a suggestion only with a reason', async () => {
    const element = await render();
    button(element, 'Rechazar').click();
    await settle(fixture);

    button(element, 'Rechazar con este motivo').click();
    await settle(fixture);
    expect(text(fixture)).toContain('Indica el motivo del rechazo.');
    expect(ai['decide']).not.toHaveBeenCalled();

    const reason = element.querySelector('textarea')!;
    reason.value = 'Es de otro cliente';
    reason.dispatchEvent(new Event('input'));
    button(element, 'Rechazar con este motivo').click();
    await settle(fixture);
    expect(ai['decide']).toHaveBeenCalledWith('s1', 0, 'reject', 'Es de otro cliente');
    expect(close).not.toHaveBeenCalled();
  });

  it('explains a failed job and the demo recordings', async () => {
    await render(
      { id: 's1', status: 'failed', progress: 0, error_code: 'no_candidates' },
      { available: true, used_today: 0, daily_limit: null },
    );

    expect(text(fixture)).toContain('No hay cobros con saldo disponible para sugerir.');
    expect(text(fixture)).toContain('En la demo, las respuestas de la IA son grabaciones.');
  });
});
