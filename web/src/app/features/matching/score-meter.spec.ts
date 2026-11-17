import { TestBed } from '@angular/core/testing';

import { litBars, ScoreMeter } from './score-meter.component';

describe('litBars', () => {
  it('lights one bar per 20 points, rounded, between none and five', () => {
    expect([100, 95, 85, 80, 75, 60, 0].map(litBars)).toEqual([5, 5, 4, 4, 4, 3, 0]);
    expect(litBars(140)).toBe(5);
    expect(litBars(-5)).toBe(0);
  });
});

describe('ScoreMeter', () => {
  it('shows the number and hides the bars from assistive technology', async () => {
    const fixture = TestBed.createComponent(ScoreMeter);
    fixture.componentRef.setInput('score', 85);
    await fixture.whenStable();
    const element = fixture.nativeElement as HTMLElement;

    expect(element.textContent?.trim()).toBe('85');
    expect(element.querySelector('.meter')?.getAttribute('aria-hidden')).toBe('true');
    expect(element.querySelectorAll('.meter__bar--lit')).toHaveLength(4);
  });
});
