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

  describe('scheme', () => {
    let listeners: ((event: { matches: boolean }) => void)[];

    beforeEach(() => {
      listeners = [];
      vi.stubGlobal(
        'matchMedia',
        vi.fn(() => ({
          matches: true,
          addEventListener: (_: string, listener: (event: { matches: boolean }) => void) =>
            listeners.push(listener),
          removeEventListener: vi.fn(),
        })),
      );
    });

    afterEach(() => vi.unstubAllGlobals());

    it('is the chosen scheme, or the system one while following it', () => {
      const theme = create();

      expect(theme.scheme()).toBe('dark');
      listeners.forEach((listener) => listener({ matches: false }));
      expect(theme.scheme()).toBe('light');
      theme.mode.set('dark');
      expect(theme.scheme()).toBe('dark');
    });
  });
});
