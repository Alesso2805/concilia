import { TestBed } from '@angular/core/testing';

import { ThemeService } from './theme.service';

describe('ThemeService', () => {
  const root = document.documentElement;

  beforeEach(() => {
    localStorage.clear();
    delete root.dataset['theme'];
  });

  function create(): ThemeService {
    TestBed.resetTestingModule();
    const service = TestBed.inject(ThemeService);
    TestBed.tick();
    return service;
  }

  it('follows the system by default', () => {
    const theme = create();

    expect(theme.mode()).toBe('system');
    expect(root.dataset['theme']).toBeUndefined();
  });

  it('applies and remembers a chosen theme', () => {
    const theme = create();

    theme.mode.set('dark');
    TestBed.tick();

    expect(root.dataset['theme']).toBe('dark');
    expect(create().mode()).toBe('dark');
  });

  it('goes back to the system theme', () => {
    localStorage.setItem('concilia.theme', 'light');
    const theme = create();

    theme.mode.set('system');
    TestBed.tick();

    expect(root.dataset['theme']).toBeUndefined();
    expect(localStorage.getItem('concilia.theme')).toBeNull();
  });
});
