# ADR-0011: A ledger-style visual design on Angular Material 3

- Status: Accepted
- Date: 2026-11-17
- Story: CN-25

## Context

The interface used Angular Material 3 almost untouched: the azure palette, Roboto, pill buttons and an empty top bar. It worked and passed axe, but it looked like every Material demo and said nothing about reconciliation. For a portfolio, the first screens a visitor sees matter.

The owner compared three directions on a design canvas. The first was a light ledger. The second was a dark-first control room with a side panel for details. The third was a warm theme with copper and indigo and summary cards in the inbox. The owner chose the ledger, with a dark mode.

## Decision

**Stay on Angular Material 3 and change its theme, not its components.** The look comes from palettes, typography, shapes and a few token overrides, so every screen inherits it, and the components keep their keyboard and screen-reader behavior.

- **Palettes.** `ng generate @angular/material:theme-color` builds `web/src/_theme-colors.scss` from three seeds:
  - green `#1D6B50` for the primary color, "it adds up";
  - amber `#9A5410` for the tertiary color, which marks differences, demo badges and anything that needs a second look;
  - a warm grey `#74786F` for neutrals.
  Material derives every role in light and dark from them, so contrast follows the M3 tonal rules.
- **Dark mode.** It is the existing mechanism: `mat.theme` emits `light-dark()` values, `color-scheme` picks one, and the theme menu (system, light, dark) sets `data-theme`. Surfaces that Material does not cover use the same `light-dark()` pattern (`--app-panel`).
- **Type.** Inter for the interface. Amounts, dates and document numbers use JetBrains Mono with tabular figures (`.app-amount`), so columns of money align like a ledger. Both are installed with `@fontsource` and served by the app, as the CSP requires.
- **Shape.** 8 px corners on buttons, fields and navigation items, and 10–12 px on cards and dialogs, instead of M3's pills.
- **Layout.** The side menu carries:
  - the logo, two bars of equal length;
  - the organization and its demo badge;
  - the items grouped into "Conciliación", "Control" and "Administración".

  The top bar names the section and the page. The demo role switch stays in the top bar, where the guided tour points to it.
- **Behavior does not change.** The match detail stays in its dialog, restyled. Moving it inline would have to bring along the difference-reason form, the reasons for rejecting and reverting, and the reviewer's actions.

## Consequences

- One theme file and a few overrides restyle every screen; new screens look right without extra work.
- The palettes are generated, so changing a seed means running the schematic again, not editing tones by hand.
- Playwright runs axe on every screen in light and dark, so a contrast regression in either mode fails CI.
- Inter and JetBrains Mono add about 140 KB of fonts (six Latin WOFF2 files), cached after the first visit.

## Alternatives considered

- **Dark-first "control room".** It looks the most modern, but it is harder on the eyes for long reconciliation sessions. Its side detail panel would also change how the inbox works.
- **Warm copper and indigo.** It is the most memorable, but its summary cards repeat the dashboard inside the inbox, and its large radii and pills fit a consumer app better than a back office.
- **A custom component library or Tailwind.** Rejected: it would replace accessible, tested Material components to change how they look, which the theme already allows.
