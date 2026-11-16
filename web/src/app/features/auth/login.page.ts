import { ChangeDetectionStrategy, Component, inject, input, signal } from '@angular/core';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { Router } from '@angular/router';

import { INVITATION_PATH, ORGANIZATION_PICKER_PATH, safeReturnUrl } from '../../core/session/paths';
import { SessionStore } from '../../core/session/session.store';
import { DEMO_LANDING } from '../demo/demo-start.page';
import { demoErrorMessage, loginErrorMessage } from './login-errors';

@Component({
  selector: 'app-login-page',
  imports: [
    ReactiveFormsModule,
    MatButtonModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
  ],
  templateUrl: './login.page.html',
  styleUrl: './auth-card.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LoginPage {
  private readonly store = inject(SessionStore);
  private readonly router = inject(Router);

  readonly volver = input<string>();

  protected readonly form = inject(NonNullableFormBuilder).group({
    email: ['', [Validators.required, Validators.email]],
    password: ['', Validators.required],
  });
  protected readonly submitting = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly startingDemo = signal(false);
  protected readonly demoError = signal<string | null>(null);

  protected async startDemo(): Promise<void> {
    this.startingDemo.set(true);
    this.demoError.set(null);
    try {
      await this.store.startDemo();
      await this.router.navigateByUrl(DEMO_LANDING);
    } catch (error) {
      this.demoError.set(demoErrorMessage(error));
    } finally {
      this.startingDemo.set(false);
    }
  }

  protected async submit(): Promise<void> {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    this.submitting.set(true);
    this.error.set(null);
    try {
      const { email, password } = this.form.getRawValue();
      const result = await this.store.login(email, password);
      const volver = safeReturnUrl(this.volver());
      if (result.organization_id || volver.startsWith(INVITATION_PATH)) {
        await this.router.navigateByUrl(volver);
      } else if (result.organizations.length > 0) {
        await this.router.navigate([ORGANIZATION_PICKER_PATH], { queryParams: { volver } });
      } else {
        this.error.set('Tu cuenta no pertenece a ninguna organización activa.');
      }
    } catch (error) {
      this.error.set(loginErrorMessage(error));
    } finally {
      this.submitting.set(false);
    }
  }
}
