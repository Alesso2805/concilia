import { DatePipe } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  OnInit,
  signal,
} from '@angular/core';
import { FormControl, FormGroup, ReactiveFormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatPaginatorIntl, MatPaginatorModule, PageEvent } from '@angular/material/paginator';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSelectModule } from '@angular/material/select';
import { MatTableModule } from '@angular/material/table';

import { AuditAction } from '../../api/models/audit-action';
import { AuditActorView } from '../../api/models/audit-actor-view';
import { AuditEntity } from '../../api/models/audit-entity';
import { AuditEventView } from '../../api/models/audit-event-view';
import { AuditPageView } from '../../api/models/audit-page-view';
import { KeysetPaginatorIntl, keysetLength } from '../../core/paging/keyset';
import {
  AUDIT_PAGE_SIZE,
  AuditCursor,
  auditErrorMessage,
  AuditFilters,
  AuditService,
  NO_AUDIT_FILTERS,
} from './audit.service';
import { ACTION_LABELS, ENTITY_LABELS, metadataSummary } from './labels';

const ACTIONS = Object.keys(ACTION_LABELS) as AuditAction[];
const ENTITIES = Object.keys(ENTITY_LABELS) as AuditEntity[];

@Component({
  selector: 'app-audit-page',
  imports: [
    DatePipe,
    ReactiveFormsModule,
    MatButtonModule,
    MatFormFieldModule,
    MatInputModule,
    MatPaginatorModule,
    MatProgressBarModule,
    MatSelectModule,
    MatTableModule,
  ],
  providers: [{ provide: MatPaginatorIntl, useClass: KeysetPaginatorIntl }],
  templateUrl: './audit.page.html',
  styleUrl: './audit.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AuditPage implements OnInit {
  private readonly audit = inject(AuditService);

  protected readonly columns = ['at', 'actor', 'action', 'entity', 'detail'];
  protected readonly actions = ACTIONS;
  protected readonly entities = ENTITIES;
  protected readonly actionLabels = ACTION_LABELS;
  protected readonly entityLabels = ENTITY_LABELS;
  protected readonly pageSize = AUDIT_PAGE_SIZE;

  protected readonly actors = signal<AuditActorView[]>([]);
  protected readonly filters = signal<AuditFilters>(NO_AUDIT_FILTERS);
  protected readonly page = signal<AuditPageView | null>(null);
  protected readonly pageIndex = signal(0);
  protected readonly error = signal<string | null>(null);
  protected readonly length = computed(() =>
    keysetLength(this.pageIndex(), AUDIT_PAGE_SIZE, this.page()?.has_next ?? false),
  );
  protected readonly form = new FormGroup({
    actorUserId: new FormControl<string | null>(null),
    action: new FormControl<AuditAction | null>(null),
    entity: new FormControl<AuditEntity | null>(null),
    from: new FormControl('', { nonNullable: true }),
    to: new FormControl('', { nonNullable: true }),
  });

  async ngOnInit(): Promise<void> {
    try {
      this.actors.set(await this.audit.actors());
    } catch (error) {
      this.error.set(auditErrorMessage(error));
    }
    await this.load({});
  }

  protected actionOf(event: AuditEventView): string {
    return ACTION_LABELS[event.action];
  }

  protected entityOf(event: AuditEventView): string {
    return ENTITY_LABELS[event.entity];
  }

  protected detailOf(event: AuditEventView): string {
    return metadataSummary(event.metadata);
  }

  protected async apply(): Promise<void> {
    const value = this.form.getRawValue();
    this.filters.set({
      actorUserId: value.actorUserId,
      action: value.action,
      entity: value.entity,
      from: value.from || null,
      to: value.to || null,
    });
    await this.restart();
  }

  protected async clear(): Promise<void> {
    this.form.reset();
    this.filters.set(NO_AUDIT_FILTERS);
    await this.restart();
  }

  protected async turn(event: PageEvent): Promise<void> {
    const view = this.page();
    if (!view) {
      return;
    }
    const forward = event.pageIndex > this.pageIndex();
    this.pageIndex.set(event.pageIndex);
    await this.load(forward ? { after: view.next_cursor } : { before: view.previous_cursor });
  }

  private async restart(): Promise<void> {
    this.pageIndex.set(0);
    this.page.set(null);
    await this.load({});
  }

  private async load(cursor: AuditCursor): Promise<void> {
    const filters = this.filters();
    try {
      const view = await this.audit.events(filters, cursor);
      if (filters === this.filters()) {
        this.page.set(view);
        this.error.set(null);
      }
    } catch (error) {
      this.error.set(auditErrorMessage(error));
    }
  }
}
