import { HttpContextToken } from '@angular/common/http';

export const REDIRECT_ON_401 = new HttpContextToken<boolean>(() => true);
