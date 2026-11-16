import { newId } from './ids';

const UUID_V7 = /^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

describe('newId', () => {
  it('generates uuid v7 values in increasing order', () => {
    const ids = Array.from({ length: 100 }, () => newId());

    expect(ids.every((id) => UUID_V7.test(id))).toBe(true);
    expect([...ids].sort()).toEqual(ids);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('embeds the current time', () => {
    const before = Date.now();
    const millis = parseInt(newId().replace(/-/g, '').slice(0, 12), 16);

    expect(millis).toBeGreaterThanOrEqual(before);
    expect(millis).toBeLessThanOrEqual(Date.now());
  });
});
