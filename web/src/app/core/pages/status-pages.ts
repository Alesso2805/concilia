import { ChangeDetectionStrategy, Component } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { RouterLink } from '@angular/router';

@Component({
  selector: 'app-not-found-page',
  imports: [RouterLink, MatButtonModule, MatIconModule],
  template: `
    <section class="status-page">
      <mat-icon class="status-page__icon" svgIcon="search_off" />
      <h1 class="status-page__title">No encontramos esta página</h1>
      <p class="status-page__text">Revisa la dirección o vuelve al inicio.</p>
      <a mat-flat-button routerLink="/">Volver al inicio</a>
    </section>
  `,
  styleUrl: './status-page.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class NotFoundPage {}

@Component({
  selector: 'app-forbidden-page',
  imports: [RouterLink, MatButtonModule, MatIconModule],
  template: `
    <section class="status-page">
      <mat-icon class="status-page__icon" svgIcon="block" />
      <h1 class="status-page__title">No tienes acceso a esta sección</h1>
      <p class="status-page__text">
        Tus roles no incluyen esta página. Si lo necesitas, pide acceso a quien administra tu
        organización.
      </p>
      <a mat-flat-button routerLink="/">Volver al inicio</a>
    </section>
  `,
  styleUrl: './status-page.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ForbiddenPage {}

// Kept in the initial bundle and linked with a full reload: it is the fallback when a
// lazy chunk fails to load, typically right after a deployment.
@Component({
  selector: 'app-error-page',
  imports: [MatButtonModule, MatIconModule],
  template: `
    <main class="status-page">
      <mat-icon class="status-page__icon" svgIcon="error" />
      <h1 class="status-page__title">Algo salió mal</h1>
      <p class="status-page__text">
        No pudimos cargar esta parte de la aplicación. Vuelve al inicio para intentarlo de nuevo.
      </p>
      <a mat-flat-button href="/">Volver al inicio</a>
    </main>
  `,
  styleUrl: './status-page.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ErrorPage {}
