import { ChangeDetectionStrategy, Component } from '@angular/core';

@Component({
  selector: 'app-logo',
  template: `
    <svg viewBox="0 0 28 28" aria-hidden="true" focusable="false">
      <rect class="logo__tile" width="28" height="28" rx="7" />
      <rect class="logo__bar" x="7" y="9.5" width="14" height="2.6" rx="1.3" />
      <rect class="logo__bar" x="7" y="15.9" width="14" height="2.6" rx="1.3" />
    </svg>
  `,
  styles: `
    :host {
      display: inline-flex;
      width: 28px;
      height: 28px;
      flex: none;
    }

    svg {
      width: 100%;
      height: 100%;
    }

    .logo__tile {
      fill: var(--mat-sys-primary);
    }

    .logo__bar {
      fill: var(--mat-sys-on-primary);
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LogoComponent {}
