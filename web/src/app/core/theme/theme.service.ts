import { DOCUMENT } from '@angular/common';
import { effect, inject, Injectable, signal } from '@angular/core';

import { IconName } from '../icons';

export type ThemeMode = 'system' | 'light' | 'dark';

export const THEME_OPTIONS: readonly { mode: ThemeMode; label: string; icon: IconName }[] = [
  { mode: 'system', label: 'Según el sistema', icon: 'contrast' },
  { mode: 'light', label: 'Claro', icon: 'light_mode' },
  { mode: 'dark', label: 'Oscuro', icon: 'dark_mode' },
];

const STORAGE_KEY = 'concilia.theme';

function stored(storage: Storage | undefined): ThemeMode {
  const value = storage?.getItem(STORAGE_KEY);
  return value === 'light' || value === 'dark' ? value : 'system';
}

@Injectable({ providedIn: 'root' })
export class ThemeService {
  private readonly root = inject(DOCUMENT).documentElement;
  private readonly storage = inject(DOCUMENT).defaultView?.localStorage;

  readonly mode = signal<ThemeMode>(stored(this.storage));

  constructor() {
    effect(() => {
      const mode = this.mode();
      if (mode === 'system') {
        delete this.root.dataset['theme'];
        this.storage?.removeItem(STORAGE_KEY);
      } else {
        this.root.dataset['theme'] = mode;
        this.storage?.setItem(STORAGE_KEY, mode);
      }
    });
  }
}
