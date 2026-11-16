import { HttpErrorResponse, HttpStatusCode } from '@angular/common/http';

export function loginErrorMessage(error: unknown): string {
  if (error instanceof HttpErrorResponse) {
    if (error.status === HttpStatusCode.Unauthorized) {
      return 'El correo o la contraseña no son correctos.';
    }
    if (error.status === HttpStatusCode.TooManyRequests) {
      return 'Hubo demasiados intentos. Espera unos minutos y vuelve a intentarlo.';
    }
  }
  return 'No pudimos conectar con el servidor. Intenta de nuevo.';
}
