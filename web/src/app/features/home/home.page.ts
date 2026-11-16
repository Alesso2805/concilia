import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';

import { roleLabel } from '../../core/session/roles';
import { SessionStore } from '../../core/session/session.store';

@Component({
  selector: 'app-home-page',
  template: `
    <h1>Inicio</h1>
    @if (organization(); as organization) {
      <p>Estás en {{ organization.name }}. Tus roles: {{ roles() }}.</p>
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class HomePage {
  private readonly store = inject(SessionStore);

  protected readonly organization = this.store.organization;
  protected readonly roles = computed(() => [...this.store.roles()].map(roleLabel).join(', '));
}
