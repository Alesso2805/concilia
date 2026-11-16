import { ChangeDetectionStrategy, Component, inject, OnInit, signal } from '@angular/core';
import {
  AbstractControl,
  NonNullableFormBuilder,
  ReactiveFormsModule,
  ValidationErrors,
  Validators,
} from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSnackBar } from '@angular/material/snack-bar';

import { parsePercent, parseSoles, percentInput, solesInput } from '../../core/format/amounts';
import { SessionStore } from '../../core/session/session.store';
import { BankingService, bankingErrorMessage } from './banking.service';

const MAX_RATES = 5;

function parseRates(text: string): number[] | null {
  const parts = text.split(/[;\s]+|,\s+/).filter(Boolean);
  const rates = parts.map(parsePercent);
  if (rates.some((rate) => rate === null || rate === 0) || rates.length > MAX_RATES) {
    return null;
  }
  const values = rates as number[];
  return new Set(values).size === values.length ? values : null;
}

function parsed(parse: (text: string) => unknown) {
  return (control: AbstractControl<string>): ValidationErrors | null =>
    parse(control.value) === null ? { format: true } : null;
}

@Component({
  selector: 'app-settings-page',
  imports: [
    ReactiveFormsModule,
    MatButtonModule,
    MatFormFieldModule,
    MatInputModule,
    MatProgressBarModule,
  ],
  templateUrl: './settings.page.html',
  styleUrl: './admin-page.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SettingsPage implements OnInit {
  private readonly banking = inject(BankingService);
  private readonly session = inject(SessionStore);
  private readonly snackBar = inject(MatSnackBar);

  protected readonly form = inject(NonNullableFormBuilder).group({
    name: ['', [Validators.required, Validators.maxLength(200)]],
    toleranceMin: ['', [Validators.required, parsed(parseSoles)]],
    tolerancePercent: ['', [Validators.required, parsed(parsePercent)]],
    detractionRates: ['', parsed(parseRates)],
  });
  protected readonly loaded = signal(false);
  protected readonly saving = signal(false);
  protected readonly error = signal<string | null>(null);

  async ngOnInit(): Promise<void> {
    try {
      const settings = await this.banking.settings();
      this.form.setValue({
        name: settings.name,
        toleranceMin: solesInput(settings.tolerance_min_cents),
        tolerancePercent: percentInput(settings.tolerance_bp),
        detractionRates: settings.detraction_rates_bp.map(percentInput).join('; '),
      });
      this.loaded.set(true);
    } catch (error) {
      this.error.set(bankingErrorMessage(error));
    }
  }

  protected async save(): Promise<void> {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    const value = this.form.getRawValue();
    this.saving.set(true);
    this.error.set(null);
    try {
      await this.banking.updateSettings({
        name: value.name.trim(),
        tolerance_min_cents: parseSoles(value.toleranceMin) ?? 0,
        tolerance_bp: parsePercent(value.tolerancePercent) ?? 0,
        detraction_rates_bp: parseRates(value.detractionRates) ?? [],
      });
      await this.session.refresh();
      this.snackBar.open('Configuración guardada.', 'Cerrar', { duration: 4000 });
    } catch (error) {
      this.error.set(bankingErrorMessage(error));
    } finally {
      this.saving.set(false);
    }
  }
}
