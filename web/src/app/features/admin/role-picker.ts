import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import {
  AbstractControl,
  FormControl,
  FormGroup,
  ReactiveFormsModule,
  ValidationErrors,
} from '@angular/forms';
import { MatCheckboxModule } from '@angular/material/checkbox';

import { RoleName } from '../../api/models/role-name';
import { ROLE_LABELS } from '../../core/session/roles';

export const ROLE_NAMES: readonly RoleName[] = ['admin', 'analyst', 'reviewer'];

export type RoleControls = Record<RoleName, FormControl<boolean>>;

export function atLeastOneRole(group: AbstractControl): ValidationErrors | null {
  return Object.values(group.value as Record<string, boolean>).some(Boolean)
    ? null
    : { roles: true };
}

export function roleGroup(selected: readonly RoleName[] = []): FormGroup<RoleControls> {
  const controls = Object.fromEntries(
    ROLE_NAMES.map((role) => [
      role,
      new FormControl(selected.includes(role), { nonNullable: true }),
    ]),
  ) as RoleControls;
  return new FormGroup(controls, { validators: atLeastOneRole });
}

export function selectedRoles(group: FormGroup<RoleControls>): RoleName[] {
  const value = group.getRawValue();
  return ROLE_NAMES.filter((role) => value[role]);
}

@Component({
  selector: 'app-role-picker',
  imports: [ReactiveFormsModule, MatCheckboxModule],
  template: `
    <fieldset class="roles" [formGroup]="group()">
      <legend class="roles__legend">Roles</legend>
      @for (role of roles; track role) {
        <mat-checkbox [formControlName]="role">{{ labels[role] }}</mat-checkbox>
      }
      @if (group().touched && group().hasError('roles')) {
        <p class="roles__error" role="alert">Elige al menos un rol.</p>
      }
    </fieldset>
  `,
  styles: `
    .roles {
      display: grid;
      margin: 0;
      padding: 0;
      border: 0;
    }
    .roles__legend {
      margin-bottom: 4px;
      font: var(--mat-sys-title-small);
    }
    .roles__error {
      margin: 0;
      color: var(--mat-sys-error);
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RolePicker {
  readonly group = input.required<FormGroup<RoleControls>>();
  protected readonly roles = ROLE_NAMES;
  protected readonly labels = ROLE_LABELS;
}
