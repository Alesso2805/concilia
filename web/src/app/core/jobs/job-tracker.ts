import { inject, Injectable } from '@angular/core';
import { Observable, switchMap, takeUntil, takeWhile, timer } from 'rxjs';

import { Api } from '../../api/api';
import { getJob } from '../../api/functions';
import { JobView } from '../../api/models/job-view';

export const POLL_INTERVAL_MS = 2_000;
export const GIVE_UP_AFTER_MS = 5 * 60_000;

export function isFinished(job: JobView): boolean {
  return job.status === 'done' || job.status === 'failed';
}

@Injectable({ providedIn: 'root' })
export class JobTracker {
  private readonly api = inject(Api);

  /** Emits the job every 2 s until it finishes; completes without finishing after 5 minutes. */
  track(jobId: string): Observable<JobView> {
    return timer(0, POLL_INTERVAL_MS).pipe(
      switchMap(() => this.api.invoke(getJob, { job_id: jobId })),
      takeWhile((job) => !isFinished(job), true),
      takeUntil(timer(GIVE_UP_AFTER_MS)),
    );
  }
}
