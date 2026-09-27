import { describe, expect, it } from 'vitest';
import { locationLabel } from '../lib/locations';

describe('locationLabel', () => {
  it('알려진 코드는 한국어 라벨로', () => {
    expect(locationLabel('title')).toBe('페이지 제목');
    expect(locationLabel('ad_copy')).toBe('광고 문구');
  });

  it('모바일 접두어를 붙인다', () => {
    expect(locationLabel('mobile:body')).toBe('모바일 본문');
  });

  it('모르는 코드는 그대로 — 새 필드가 생겨도 빈칸이 되지 않는다', () => {
    expect(locationLabel('new_field')).toBe('new_field');
  });
});
