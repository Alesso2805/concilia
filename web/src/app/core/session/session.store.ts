import { HttpContext, HttpErrorResponse } from '@angular/common/http';
import { computed, inject, Injectable, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { Api } from '../../api/api';
import {
  chooseOrganization,
  createDemo,
  getSession,
  login,
  logout,
  switchDemoRole,
} from '../../api/functions';
import { LoginView } from '../../api/models/login-view';
import { SessionView } from '../../api/models/session-view';
import { REDIRECT_ON_401 } from '../http/context';
import { Role } from './roles';

@Injectable({ providedIn: 'root' })
export class SessionStore {
  private readonly api = inject(Api);
  private readonly current = signal<SessionView | null>(null);
  private restoring: Promise<SessionView | null> | null = null;

  readonly session = this.current.asReadonly();
  readonly organization = computed(() => {
    const session = this.current();
    return session?.organizations.find((o) => o.id === session.organization_id) ?? null;
  });
  readonly roles = computed(() => new Set(this.current()?.roles ?? []));

  hasAnyRole(roles: readonly Role[]): boolean {
    const granted = this.roles();
    return roles.some((role) => granted.has(role));
  }

  restore(): Promise<SessionView | null> {
    this.restoring ??= this.fetch();
    return this.restoring;
  }

  async login(email: string, password: string): Promise<LoginView> {
    const result = await firstValueFrom(this.api.invoke(login, { body: { email, password } }));
    await this.refresh();
    return result;
  }

  async chooseOrganization(organizationId: string): Promise<void> {
    await firstValueFrom(
      this.api.invoke(chooseOrganization, { body: { organization_id: organizationId } }),
    );
    await this.refresh();
  }

  /** Creates a demo organization with fictional data and signs in as its analyst. */
  async startDemo(): Promise<void> {
    await firstValueFrom(this.api.invoke(createDemo));
    await this.refresh();
  }

  /** Continues the demo as its user with another role, in a new session. */
  async switchDemoRole(role: Role): Promise<void> {
    await firstValueFrom(this.api.invoke(switchDemoRole, { body: { role } }));
    await this.refresh();
  }

  async logout(): Promise<void> {
    try {
      await firstValueFrom(this.api.invoke(logout));
    } finally {
      this.forget();
    }
  }

  forget(): void {
    this.current.set(null);
    this.restoring = Promise.resolve(null);
  }

  refresh(): Promise<SessionView | null> {
    this.restoring = null;
    return this.restore();
  }

  private async fetch(): Promise<SessionView | null> {
    const quiet = new HttpContext().set(REDIRECT_ON_401, false);
    try {
      const session = await firstValueFrom(this.api.invoke(getSession, {}, quiet));
      this.current.set(session);
      return session;
    } catch (error) {
      if (error instanceof HttpErrorResponse && error.status === 401) {
        this.current.set(null);
        return null;
      }
      this.restoring = null;
      throw error;
    }
  }
}
