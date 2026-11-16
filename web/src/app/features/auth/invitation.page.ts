import { DOCUMENT, Location } from '@angular/common';
import { ChangeDetectionStrategy, Component, inject, OnInit, signal } from '@angular/core';
import { NonNullableFormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import { INVITATION_PATH, LOGIN_PATH } from '../../core/session/paths';
import { SessionStore } from '../../core/session/session.store';
import { InvitationService, invitationErrorMessage } from './invitation.service';

const TOKEN_KEY = 'concilia.invitation';
const MIN_PASSWORD_LENGTH = 12;

type State = 'loading' | 'missing' | 'signed-in' | 'new-account';

@Component({
  selector: 'app-invitation-page',
  imports: [
    ReactiveFormsModule,
    RouterLink,
    MatButtonModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatProgressBarModule,
  ],
  templateUrl: './invitation.page.html',
  styleUrl: './auth-card.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class InvitationPage implements OnInit {
  private readonly store = inject(SessionStore);
  private readonly invitations = inject(InvitationService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly location = inject(Location);
  private readonly storage = inject(DOCUMENT).defaultView?.sessionStorage;

  protected readonly loginPath = LOGIN_PATH;
  protected readonly invitationPath = INVITATION_PATH;
  protected readonly state = signal<State>('loading');
  protected readonly working = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly form = inject(NonNullableFormBuilder).group({
    email: ['', [Validators.required, Validators.email]],
    display_name: ['', Validators.required],
    password: ['', [Validators.required, Validators.minLength(MIN_PASSWORD_LENGTH)]],
  });

  private token: string | null = null;

  async ngOnInit(): Promise<void> {
    const fragment = this.route.snapshot.fragment;
    if (fragment) {
      this.storage?.setItem(TOKEN_KEY, fragment);
      this.location.replaceState(INVITATION_PATH);
    }
    this.token = fragment || (this.storage?.getItem(TOKEN_KEY) ?? null);
    if (!this.token) {
      this.state.set('missing');
      return;
    }
    const session = await this.store.restore().catch(() => null);
    this.state.set(session ? 'signed-in' : 'new-account');
  }

  protected acceptAsMember(): Promise<void> {
    return this.run(async (token) => {
      const organizationId = await this.invitations.acceptAsMember(token);
      await this.store.chooseOrganization(organizationId);
    });
  }

  protected createAccount(): Promise<void> {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return Promise.resolve();
    }
    return this.run(async (token) => {
      await this.invitations.acceptWithNewAccount(token, this.form.getRawValue());
      await this.store.refresh();
    });
  }

  private async run(accept: (token: string) => Promise<void>): Promise<void> {
    if (!this.token) {
      return;
    }
    this.working.set(true);
    this.error.set(null);
    try {
      await accept(this.token);
      this.storage?.removeItem(TOKEN_KEY);
      await this.router.navigateByUrl('/');
    } catch (error) {
      this.error.set(invitationErrorMessage(error));
    } finally {
      this.working.set(false);
    }
  }
}
