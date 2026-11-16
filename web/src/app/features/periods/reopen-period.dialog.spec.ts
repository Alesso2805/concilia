import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';

import { ReopenPeriodDialog } from './reopen-period.dialog';

describe('ReopenPeriodDialog', () => {
  let fixture: ComponentFixture<ReopenPeriodDialog>;
  let close: ReturnType<typeof vi.fn>;

  beforeEach(async () => {
    close = vi.fn();
    TestBed.configureTestingModule({
      imports: [ReopenPeriodDialog],
      providers: [
        { provide: MAT_DIALOG_DATA, useValue: 'enero de 2027' },
        { provide: MatDialogRef, useValue: { close } },
      ],
    });
    fixture = TestBed.createComponent(ReopenPeriodDialog);
    await fixture.whenStable();
  });

  function submit(reason: string): HTMLElement {
    const element = fixture.nativeElement as HTMLElement;
    const textarea = element.querySelector('textarea')!;
    textarea.value = reason;
    textarea.dispatchEvent(new Event('input'));
    element.querySelector('form')!.dispatchEvent(new Event('submit'));
    fixture.detectChanges();
    return element;
  }

  it('names the month and asks for a reason before reopening it', () => {
    const element = submit('   ');

    expect(element.textContent).toContain('Reabrir enero de 2027');
    expect(element.textContent).toContain('Indica el motivo.');
    expect(close).not.toHaveBeenCalled();
  });

  it('closes with the trimmed reason', () => {
    submit('  Faltó un abono  ');

    expect(close).toHaveBeenCalledWith('Faltó un abono');
  });
});
