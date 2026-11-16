import { ChangeDetectionStrategy, Component, inject, OnInit, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { Router, RouterLink } from '@angular/router';

import { SessionStore } from '../../core/session/session.store';
import { demoErrorMessage } from '../auth/login-errors';

export const DEMO_LANDING = '/bandeja';

/** A shareable link that creates a demo and opens it, the same as "Probar la demo". */
@Component({
  selector: 'app-demo-start-page',
  imports: [MatButtonModule, MatCardModule, MatProgressBarModule, RouterLink],
  template: `
    <main class="auth">
      <mat-card appearance="outlined" class="auth__card">
        <mat-card-header>
          <mat-card-title><h1 class="auth__title">Concilia</h1></mat-card-title>
          <mat-card-subtitle>Demo con datos ficticios</mat-card-subtitle>
        </mat-card-header>
        <mat-card-content class="auth__content">
          @if (error(); as message) {
            <p class="auth__error" role="alert">{{ message }}</p>
            <a mat-stroked-button routerLink="/iniciar-sesion">Ir al inicio de sesión</a>
          } @else {
            <p aria-live="polite">Preparando tu demo…</p>
            <mat-progress-bar mode="indeterminate" aria-label="Preparando la demo" />
          }
        </mat-card-content>
      </mat-card>
    </main>
  `,
  styleUrl: '../auth/auth-card.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DemoStartPage implements OnInit {
  private readonly store = inject(SessionStore);
  private readonly router = inject(Router);

  protected readonly error = signal<string | null>(null);

  async ngOnInit(): Promise<void> {
    try {
      await this.store.startDemo();
      await this.router.navigateByUrl(DEMO_LANDING);
    } catch (error) {
      this.error.set(demoErrorMessage(error));
    }
  }
}
