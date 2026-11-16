import { ChangeDetectionStrategy, Component, computed, effect, input, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { RouterLink } from '@angular/router';

export interface TourStep {
  title: string;
  role: string;
  text: string;
  path: string;
  link: string;
}

export const TOUR_STEPS: readonly TourStep[] = [
  {
    title: 'Importa el tercer mes',
    role: 'Análisis',
    text: 'Descarga el extracto de diciembre de la demo y súbelo con el perfil «Extracto de la demo (CSV)». La vista previa marca los movimientos que ya estaban importados.',
    path: '/importaciones',
    link: 'Ir a Importaciones',
  },
  {
    title: 'Corre el motor',
    role: 'Análisis',
    text: 'En la Bandeja, elige noviembre o diciembre y pulsa «Correr el motor». Cada propuesta trae su regla, su puntaje y una explicación.',
    path: '/bandeja',
    link: 'Ir a la Bandeja',
  },
  {
    title: 'Confirma propuestas',
    role: 'Análisis',
    text: 'Abre una propuesta y confírmala, o confirma en lote las de puntaje 100. Si hay diferencia, elige su motivo.',
    path: '/bandeja',
    link: 'Ir a la Bandeja',
  },
  {
    title: 'Pide ayuda a la IA',
    role: 'Análisis',
    text: 'En la pestaña Libres, pulsa «Pedir ayuda a la IA» en un abono. La IA solo sugiere: tú aceptas o rechazas y el sistema recalcula los montos.',
    path: '/bandeja',
    link: 'Ir a la Bandeja',
  },
  {
    title: 'Cambia a revisor y aprueba',
    role: 'Revisión',
    text: 'Usa «Ver como: Revisión» arriba. Aprueba lo confirmado: nadie aprueba lo que él mismo creó o confirmó.',
    path: '/bandeja',
    link: 'Ir a la Bandeja',
  },
  {
    title: 'Cierra el mes',
    role: 'Revisión',
    text: 'Cuando no quedan propuestas ni confirmadas en un mes, pulsa «Cerrar mes». Reabrirlo exige un motivo y queda en la auditoría.',
    path: '/bandeja',
    link: 'Ir a la Bandeja',
  },
  {
    title: 'Mira el panel y exporta',
    role: 'Análisis o Revisión',
    text: 'En el Panel ves el porcentaje conciliado, los pendientes por antigüedad y las diferencias. «Exportar a Excel» arma el reporte del mes.',
    path: '/panel',
    link: 'Ir al Panel',
  },
];

function read(key: string): number {
  try {
    const stored = Number(localStorage.getItem(key));
    return Number.isInteger(stored) && stored >= 0 && stored < TOUR_STEPS.length ? stored : 0;
  } catch {
    return 0;
  }
}

@Component({
  selector: 'app-demo-tour',
  imports: [MatButtonModule, RouterLink],
  template: `
    <div class="tour__notice" role="note">
      <strong>Demo con datos ficticios:</strong> las empresas, las personas y los montos son
      inventados.
      <button
        mat-button
        type="button"
        class="tour__toggle"
        [attr.aria-expanded]="open()"
        aria-controls="recorrido"
        (click)="open.set(!open())"
      >
        {{ open() ? 'Ocultar el recorrido' : 'Recorrido guiado' }}
      </button>
    </div>
    @if (open()) {
      <section id="recorrido" class="tour" aria-labelledby="recorrido-titulo">
        <h2 id="recorrido-titulo" class="tour__title">
          Recorrido: paso {{ current() + 1 }} de {{ steps.length }}
        </h2>
        <ol class="tour__steps">
          @for (step of steps; track step.title; let index = $index) {
            <li
              class="tour__step"
              [class.tour__step--current]="index === current()"
              [attr.aria-current]="index === current() ? 'step' : null"
            >
              <span class="tour__name">{{ step.title }}</span>
              <span class="tour__role">({{ step.role }})</span>
              @if (index === current()) {
                <p class="tour__text">{{ step.text }}</p>
                <a mat-stroked-button [routerLink]="step.path">{{ step.link }}</a>
              }
            </li>
          }
        </ol>
        <div class="tour__actions">
          <button mat-button type="button" [disabled]="current() === 0" (click)="move(-1)">
            Anterior
          </button>
          <button
            mat-flat-button
            type="button"
            [disabled]="current() === steps.length - 1"
            (click)="move(1)"
          >
            Siguiente
          </button>
        </div>
      </section>
    }
  `,
  styleUrl: './demo-tour.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DemoTour {
  readonly organizationId = input.required<string>();

  protected readonly steps = TOUR_STEPS;
  protected readonly open = signal(false);
  protected readonly current = signal(0);
  private readonly key = computed(() => `concilia.tour.${this.organizationId()}`);

  constructor() {
    effect(() => this.current.set(read(this.key())));
  }

  protected move(delta: number): void {
    const next = Math.min(Math.max(this.current() + delta, 0), TOUR_STEPS.length - 1);
    this.current.set(next);
    try {
      localStorage.setItem(this.key(), String(next));
    } catch {
      // Remembering the step is a convenience; private windows may refuse storage.
    }
  }
}
