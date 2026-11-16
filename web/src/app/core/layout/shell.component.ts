import { BreakpointObserver } from '@angular/cdk/layout';
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatListModule } from '@angular/material/list';
import { MatMenuModule } from '@angular/material/menu';
import { MatSidenavModule } from '@angular/material/sidenav';
import { MatToolbarModule } from '@angular/material/toolbar';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { map } from 'rxjs';

import { LOGIN_PATH, ORGANIZATION_PICKER_PATH } from '../session/paths';
import { Role, roleLabel } from '../session/roles';
import { SessionStore } from '../session/session.store';
import { THEME_OPTIONS, ThemeService } from '../theme/theme.service';
import { NAVIGATION, visibleItems } from './navigation';

const COMPACT_LAYOUT = '(max-width: 959.98px)';
const DEMO_ROLES: readonly Role[] = ['analyst', 'reviewer', 'admin'];
const DEMO_LANDING = '/bandeja';

@Component({
  selector: 'app-shell',
  imports: [
    RouterLink,
    RouterLinkActive,
    RouterOutlet,
    MatButtonModule,
    MatIconModule,
    MatListModule,
    MatMenuModule,
    MatSidenavModule,
    MatToolbarModule,
  ],
  templateUrl: './shell.component.html',
  styleUrl: './shell.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ShellComponent {
  private readonly store = inject(SessionStore);
  private readonly router = inject(Router);

  protected readonly theme = inject(ThemeService);
  protected readonly themeOptions = THEME_OPTIONS;
  protected readonly themeIcon = computed(
    () => THEME_OPTIONS.find((option) => option.mode === this.theme.mode())?.icon ?? 'contrast',
  );
  protected readonly organizationPickerPath = ORGANIZATION_PICKER_PATH;
  protected readonly organization = this.store.organization;
  protected readonly canSwitch = computed(
    () => (this.store.session()?.organizations.length ?? 0) > 1,
  );
  protected readonly items = computed(() => visibleItems(NAVIGATION, this.store.roles()));
  protected readonly compact = toSignal(
    inject(BreakpointObserver)
      .observe(COMPACT_LAYOUT)
      .pipe(map((state) => state.matches)),
    { initialValue: false },
  );
  protected readonly menuOpen = signal(false);
  protected readonly demoRoles = DEMO_ROLES;
  protected readonly roleLabel = roleLabel;
  protected readonly roles = this.store.roles;
  protected readonly currentRole = computed(() =>
    [...this.store.roles()].map(roleLabel).join(', '),
  );
  protected readonly switching = signal(false);

  protected async switchRole(role: Role): Promise<void> {
    if (this.store.roles().has(role)) {
      return;
    }
    this.switching.set(true);
    try {
      await this.store.switchDemoRole(role);
      await this.router.navigateByUrl(DEMO_LANDING);
    } catch {
      // The 403 interceptor already tells the visitor why the switch was refused.
    } finally {
      this.switching.set(false);
    }
  }

  protected async logout(): Promise<void> {
    // The store forgets the session even when the server call fails.
    await this.store.logout().catch(() => undefined);
    await this.router.navigate([LOGIN_PATH]);
  }
}
