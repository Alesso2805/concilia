import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { Router } from '@angular/router';

import { OrganizationView } from '../../api/models/organization-view';
import { safeReturnUrl } from '../../core/session/paths';
import { roleLabel } from '../../core/session/roles';
import { SessionStore } from '../../core/session/session.store';

@Component({
  selector: 'app-organization-page',
  imports: [MatButtonModule, MatCardModule],
  templateUrl: './organization.page.html',
  styleUrl: './auth-card.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class OrganizationPage {
  private readonly store = inject(SessionStore);
  private readonly router = inject(Router);

  readonly volver = input<string>();

  protected readonly organizations = computed(() => this.store.session()?.organizations ?? []);
  protected readonly choosing = signal(false);
  protected readonly error = signal<string | null>(null);

  protected describe(organization: OrganizationView): string {
    const roles = organization.roles.map(roleLabel).join(', ');
    return organization.is_demo ? `Demo · ${roles}` : roles;
  }

  protected async choose(organization: OrganizationView): Promise<void> {
    this.choosing.set(true);
    this.error.set(null);
    try {
      await this.store.chooseOrganization(organization.id);
      await this.router.navigateByUrl(safeReturnUrl(this.volver()));
    } catch {
      this.error.set('No pudimos abrir esa organización. Intenta de nuevo.');
    } finally {
      this.choosing.set(false);
    }
  }
}
