import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { JobView } from '../../api/models/job-view';
import { GIVE_UP_AFTER_MS, JobTracker, POLL_INTERVAL_MS } from './job-tracker';

function job(status: JobView['status'], progress = 0): JobView {
  return { id: 'j1', kind: 'parse_import', status, progress, error_code: null };
}

describe('JobTracker', () => {
  let http: HttpTestingController;
  let seen: JobView[];
  let completed: boolean;

  beforeEach(() => {
    vi.useFakeTimers();
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    http = TestBed.inject(HttpTestingController);
    seen = [];
    completed = false;
    TestBed.inject(JobTracker)
      .track('j1')
      .subscribe({ next: (value) => seen.push(value), complete: () => (completed = true) });
  });

  afterEach(() => vi.useRealTimers());

  it('polls every two seconds until the job finishes', () => {
    vi.advanceTimersByTime(0);
    http.expectOne('/api/app/jobs/j1').flush(job('running', 40));
    vi.advanceTimersByTime(POLL_INTERVAL_MS);
    http.expectOne('/api/app/jobs/j1').flush(job('done', 100));
    vi.advanceTimersByTime(POLL_INTERVAL_MS * 3);
    http.expectNone('/api/app/jobs/j1');

    expect(seen.map((value) => value.status)).toEqual(['running', 'done']);
    expect(completed).toBe(true);
  });

  it('gives up after five minutes', () => {
    for (let elapsed = 0; elapsed < GIVE_UP_AFTER_MS; elapsed += POLL_INTERVAL_MS) {
      vi.advanceTimersByTime(elapsed === 0 ? 0 : POLL_INTERVAL_MS);
      http.match('/api/app/jobs/j1').forEach((request) => request.flush(job('running')));
    }
    vi.advanceTimersByTime(POLL_INTERVAL_MS);
    http.match('/api/app/jobs/j1').forEach((request) => request.flush(job('running')));

    expect(completed).toBe(true);
    expect(seen.at(-1)?.status).toBe('running');
  });
});
