import { inject, provideAppInitializer } from '@angular/core';
import { MatIconRegistry } from '@angular/material/icon';
import { DomSanitizer } from '@angular/platform-browser';
import accountCircle from '@material-symbols/svg-400/outlined/account_circle.svg';
import block from '@material-symbols/svg-400/outlined/block.svg';
import check from '@material-symbols/svg-400/outlined/check.svg';
import contrast from '@material-symbols/svg-400/outlined/contrast.svg';
import darkMode from '@material-symbols/svg-400/outlined/dark_mode.svg';
import error from '@material-symbols/svg-400/outlined/error.svg';
import home from '@material-symbols/svg-400/outlined/home.svg';
import lightMode from '@material-symbols/svg-400/outlined/light_mode.svg';
import logout from '@material-symbols/svg-400/outlined/logout.svg';
import menu from '@material-symbols/svg-400/outlined/menu.svg';
import searchOff from '@material-symbols/svg-400/outlined/search_off.svg';
import swapHoriz from '@material-symbols/svg-400/outlined/swap_horiz.svg';

// Bundled at build time (angular.json loader) so no icon font is downloaded.
const ICONS = {
  account_circle: accountCircle,
  block,
  check,
  contrast,
  dark_mode: darkMode,
  error,
  home,
  light_mode: lightMode,
  logout,
  menu,
  search_off: searchOff,
  swap_horiz: swapHoriz,
};

export type IconName = keyof typeof ICONS;

export function provideIcons() {
  return provideAppInitializer(() => {
    const registry = inject(MatIconRegistry);
    const sanitizer = inject(DomSanitizer);
    for (const [name, svg] of Object.entries(ICONS)) {
      registry.addSvgIconLiteral(name, sanitizer.bypassSecurityTrustHtml(svg));
    }
  });
}
