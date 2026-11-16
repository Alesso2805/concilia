import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MatSnackBar } from '@angular/material/snack-bar';

import { SessionStore } from '../../core/session/session.store';
import { BankingService } from './banking.service';
import { SettingsPage } from './settings.page';

describe('SettingsPage', () => {
  let fixture: ComponentFixture<SettingsPage>;
  let updateSettings: ReturnType<typeof vi.fn>;
  let refresh: ReturnType<typeof vi.fn>;

  beforeEach(async () => {
    updateSettings = vi.fn(() => Promise.resolve());
    refresh = vi.fn(() => Promise.resolve(null));
    TestBed.configureTestingModule({
      imports: [SettingsPage],
      providers: [
        {
          provide: BankingService,
          useValue: {
            settings: () =>
              Promise.resolve({
                name: 'Andina',
                tolerance_min_cents: 100,
                tolerance_bp: 50,
                detraction_rates_bp: [1000, 1200],
              }),
            updateSettings,
          },
        },
        { provide: SessionStore, useValue: { refresh } },
        { provide: MatSnackBar, useValue: { open: vi.fn() } },
      ],
    });
    fixture = TestBed.createComponent(SettingsPage);
    await fixture.whenStable();
    await new Promise((resolve) => setTimeout(resolve));
    await fixture.whenStable();
  });

  function input(name: string): HTMLInputElement {
    return (fixture.nativeElement as HTMLElement).querySelector<HTMLInputElement>(
      `input[formcontrolname="${name}"]`,
    )!;
  }

  async function submit(): Promise<void> {
    (fixture.nativeElement as HTMLElement)
      .querySelector('form')!
      .dispatchEvent(new Event('submit'));
    await fixture.whenStable();
  }

  function type(name: string, value: string): void {
    input(name).value = value;
    input(name).dispatchEvent(new Event('input'));
  }

  it('shows amounts in soles and percentages', () => {
    expect([
      input('toleranceMin').value,
      input('tolerancePercent').value,
      input('detractionRates').value,
    ]).toEqual(['1.00', '0.5', '10; 12']);
  });

  it('saves integer cents and basis points', async () => {
    type('toleranceMin', '2,50');
    type('tolerancePercent', '0.25');
    type('detractionRates', '12; 4');
    await submit();

    expect(updateSettings).toHaveBeenCalledWith({
      name: 'Andina',
      tolerance_min_cents: 250,
      tolerance_bp: 25,
      detraction_rates_bp: [1200, 400],
    });
    expect(refresh).toHaveBeenCalled();
  });

  it.each([
    ['toleranceMin', '1.234'],
    ['tolerancePercent', 'diez'],
    ['detractionRates', '10; 10'],
    ['detractionRates', '0'],
  ])('rejects %s = %j before calling the API', async (name, value) => {
    type(name, value);
    await submit();

    expect(updateSettings).not.toHaveBeenCalled();
  });
});
