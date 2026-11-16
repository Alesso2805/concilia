import { DatePipe } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  OnInit,
  signal,
} from '@angular/core';
import { FormControl, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatPaginatorIntl, MatPaginatorModule, PageEvent } from '@angular/material/paginator';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSelectModule } from '@angular/material/select';
import { MatTableModule } from '@angular/material/table';
import { Router, RouterLink } from '@angular/router';

import { FilePageView } from '../../api/models/file-page-view';
import { ImportFileView } from '../../api/models/import-file-view';
import { KeysetPaginatorIntl, keysetLength } from '../../core/paging/keyset';
import { BankingService, ProfileView } from '../admin/banking.service';
import { ImportsService, importErrorMessage } from './imports.service';
import { STATUS_LABELS } from './labels';

const PAGE_SIZE = 10;

@Component({
  selector: 'app-imports-page',
  imports: [
    DatePipe,
    ReactiveFormsModule,
    RouterLink,
    MatButtonModule,
    MatFormFieldModule,
    MatPaginatorModule,
    MatProgressBarModule,
    MatSelectModule,
    MatTableModule,
  ],
  providers: [{ provide: MatPaginatorIntl, useClass: KeysetPaginatorIntl }],
  templateUrl: './imports.page.html',
  styleUrl: './imports.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ImportsPage implements OnInit {
  private readonly imports = inject(ImportsService);
  private readonly banking = inject(BankingService);
  private readonly router = inject(Router);

  protected readonly profiles = signal<ProfileView[]>([]);
  protected readonly profile = new FormControl('', {
    nonNullable: true,
    validators: Validators.required,
  });
  protected readonly file = signal<File | null>(null);
  protected readonly uploading = signal(false);
  protected readonly uploadError = signal<string | null>(null);
  protected readonly page = signal<FilePageView | null>(null);
  protected readonly pageIndex = signal(0);
  protected readonly listError = signal<string | null>(null);
  protected readonly pageSize = PAGE_SIZE;
  protected readonly length = computed(() =>
    keysetLength(this.pageIndex(), PAGE_SIZE, this.page()?.has_next ?? false),
  );
  protected readonly columns = ['filename', 'profile', 'status', 'created'];

  async ngOnInit(): Promise<void> {
    try {
      const profiles = await this.banking.profiles();
      this.profiles.set(
        profiles.filter((profile) => profile.kind === 'bank_statement' && !profile.archived_at),
      );
    } catch (error) {
      this.uploadError.set(importErrorMessage(error));
    }
    await this.load({});
  }

  protected statusOf(file: ImportFileView): string {
    return STATUS_LABELS[file.status];
  }

  protected choose(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.file.set(input.files?.item(0) ?? null);
    this.uploadError.set(null);
  }

  protected async upload(): Promise<void> {
    const file = this.file();
    if (this.profile.invalid || !file) {
      this.profile.markAsTouched();
      this.uploadError.set(file ? null : 'Elige el archivo del extracto.');
      return;
    }
    this.uploading.set(true);
    this.uploadError.set(null);
    try {
      const uploaded = await this.imports.upload(this.profile.value, file);
      await this.router.navigate(['/importaciones', uploaded.file.id], {
        queryParams: { trabajo: uploaded.job_id ?? undefined },
      });
    } catch (error) {
      this.uploadError.set(importErrorMessage(error));
    } finally {
      this.uploading.set(false);
    }
  }

  protected async turn(event: PageEvent): Promise<void> {
    const page = this.page();
    if (!page) {
      return;
    }
    const forward = event.pageIndex > this.pageIndex();
    this.pageIndex.set(event.pageIndex);
    await this.load(forward ? { after: page.next_cursor } : { before: page.previous_cursor });
  }

  private async load(cursor: { after?: string | null; before?: string | null }): Promise<void> {
    try {
      this.page.set(await this.imports.list(cursor));
      this.listError.set(null);
    } catch (error) {
      this.listError.set(importErrorMessage(error));
    }
  }
}
