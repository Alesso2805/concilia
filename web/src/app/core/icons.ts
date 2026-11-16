import { inject, provideAppInitializer } from '@angular/core';
import { MatIconRegistry } from '@angular/material/icon';
import { DomSanitizer } from '@angular/platform-browser';
import accountBalance from '@material-symbols/svg-400/outlined/account_balance.svg';
import accountCircle from '@material-symbols/svg-400/outlined/account_circle.svg';
import add from '@material-symbols/svg-400/outlined/add.svg';
import archive from '@material-symbols/svg-400/outlined/archive.svg';
import barChart from '@material-symbols/svg-400/outlined/bar_chart.svg';
import block from '@material-symbols/svg-400/outlined/block.svg';
import check from '@material-symbols/svg-400/outlined/check.svg';
import contentCopy from '@material-symbols/svg-400/outlined/content_copy.svg';
import contrast from '@material-symbols/svg-400/outlined/contrast.svg';
import darkMode from '@material-symbols/svg-400/outlined/dark_mode.svg';
import description from '@material-symbols/svg-400/outlined/description.svg';
import edit from '@material-symbols/svg-400/outlined/edit.svg';
import error from '@material-symbols/svg-400/outlined/error.svg';
import group from '@material-symbols/svg-400/outlined/group.svg';
import history from '@material-symbols/svg-400/outlined/history.svg';
import home from '@material-symbols/svg-400/outlined/home.svg';
import inbox from '@material-symbols/svg-400/outlined/inbox.svg';
import lightMode from '@material-symbols/svg-400/outlined/light_mode.svg';
import logout from '@material-symbols/svg-400/outlined/logout.svg';
import menu from '@material-symbols/svg-400/outlined/menu.svg';
import personAdd from '@material-symbols/svg-400/outlined/person_add.svg';
import personRemove from '@material-symbols/svg-400/outlined/person_remove.svg';
import receiptLong from '@material-symbols/svg-400/outlined/receipt_long.svg';
import searchOff from '@material-symbols/svg-400/outlined/search_off.svg';
import settings from '@material-symbols/svg-400/outlined/settings.svg';
import swapHoriz from '@material-symbols/svg-400/outlined/swap_horiz.svg';
import uploadFile from '@material-symbols/svg-400/outlined/upload_file.svg';

// Bundled at build time (angular.json loader) so no icon font is downloaded.
const ICONS = {
  account_balance: accountBalance,
  account_circle: accountCircle,
  add,
  archive,
  bar_chart: barChart,
  block,
  check,
  content_copy: contentCopy,
  contrast,
  dark_mode: darkMode,
  description,
  edit,
  error,
  group,
  history,
  home,
  inbox,
  light_mode: lightMode,
  logout,
  menu,
  person_add: personAdd,
  person_remove: personRemove,
  receipt_long: receiptLong,
  search_off: searchOff,
  settings,
  swap_horiz: swapHoriz,
  upload_file: uploadFile,
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
