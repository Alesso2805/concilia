import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  inject,
  input,
  OnInit,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NonNullableFormBuilder, ReactiveFormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatRadioModule } from '@angular/material/radio';
import { MatSelectModule } from '@angular/material/select';
import { Router, RouterLink } from '@angular/router';

import { BankAccountView } from '../../api/models/bank-account-view';
import { BankingService, ProfileView, TemplateView, bankingErrorMessage } from './banking.service';
import {
  DATE_FORMATS,
  DECIMAL_SEPARATORS,
  DELIMITERS,
  KIND_LABELS,
  RECEIVABLES_COLUMNS,
  STATEMENT_COLUMNS,
  THOUSANDS_SEPARATORS,
  applyConfig,
  profileForm,
  syncProfileForm,
  toDraft,
} from './profile-form';

const PROFILES_PATH = '/perfiles';

@Component({
  selector: 'app-profile-editor-page',
  imports: [
    ReactiveFormsModule,
    RouterLink,
    MatButtonModule,
    MatFormFieldModule,
    MatInputModule,
    MatProgressBarModule,
    MatRadioModule,
    MatSelectModule,
  ],
  templateUrl: './profile-editor.page.html',
  styleUrl: './admin-page.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ProfileEditorPage implements OnInit {
  private readonly banking = inject(BankingService);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);

  readonly id = input<string>();

  protected readonly form = profileForm(inject(NonNullableFormBuilder));
  protected readonly kinds = KIND_LABELS;
  protected readonly dateFormats = DATE_FORMATS;
  protected readonly delimiters = DELIMITERS;
  protected readonly decimalSeparators = DECIMAL_SEPARATORS;
  protected readonly thousandsSeparators = THOUSANDS_SEPARATORS;
  protected readonly statementColumns = STATEMENT_COLUMNS;
  protected readonly receivablesColumns = RECEIVABLES_COLUMNS;
  protected readonly profilesPath = PROFILES_PATH;
  protected readonly accounts = signal<BankAccountView[]>([]);
  protected readonly templates = signal<TemplateView[]>([]);
  protected readonly editing = signal<ProfileView | null>(null);
  protected readonly loaded = signal(false);
  protected readonly saving = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly templateNote = signal(false);

  async ngOnInit(): Promise<void> {
    this.form.valueChanges
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(() => syncProfileForm(this.form));
    try {
      const [accounts, templates, profiles] = await Promise.all([
        this.banking.accounts(),
        this.banking.templates(),
        this.id() ? this.banking.profiles() : Promise.resolve([]),
      ]);
      this.accounts.set(accounts.filter((account) => !account.archived_at));
      this.templates.set(templates);
      const profile = profiles.find((candidate) => candidate.id === this.id());
      if (this.id() && !profile) {
        this.error.set('Ese perfil ya no existe.');
        return;
      }
      if (profile) {
        this.editing.set(profile);
        applyConfig(this.form, profile.kind, profile.config);
        this.form.patchValue({
          name: profile.name,
          bank_account_id: profile.kind === 'bank_statement' ? profile.bank_account_id : '',
        });
        this.form.controls.kind.disable({ emitEvent: false });
        this.form.controls.bank_account_id.disable({ emitEvent: false });
      }
      syncProfileForm(this.form);
      this.loaded.set(true);
    } catch (error) {
      this.error.set(bankingErrorMessage(error));
    }
  }

  protected useTemplate(key: string): void {
    const template = this.templates().find((candidate) => candidate.key === key);
    if (!template) {
      return;
    }
    applyConfig(this.form, template.kind, template.config);
    if (!this.form.controls.name.value) {
      this.form.controls.name.setValue(template.name);
    }
    this.templateNote.set(template.kind === 'bank_statement');
  }

  protected async save(): Promise<void> {
    syncProfileForm(this.form);
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    this.saving.set(true);
    this.error.set(null);
    try {
      const draft = toDraft(this.form);
      const editing = this.editing();
      if (editing) {
        await this.banking.updateProfile(editing.id, draft);
      } else {
        await this.banking.createProfile(draft);
      }
      await this.router.navigateByUrl(PROFILES_PATH);
    } catch (error) {
      this.error.set(bankingErrorMessage(error));
    } finally {
      this.saving.set(false);
    }
  }
}
