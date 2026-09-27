import { describe, expect, it } from 'vitest';
import { parseCodes, withCode, withoutCode } from '../lib/ignore';

describe('parseCodes', () => {
  it('쉼표·공백으로 나누고 대문자로 맞추며 중복을 없앤다', () => {
    expect(parseCodes(' mis-superlative, MIS-SUPERLATIVE  dest-insufficient-content,,')).toEqual([
      'MIS-SUPERLATIVE',
      'DEST-INSUFFICIENT-CONTENT',
    ]);
  });

  it('빈 문자열은 빈 목록', () => {
    expect(parseCodes('')).toEqual([]);
  });
});

describe('withCode / withoutCode', () => {
  it('이미 있으면 다시 넣지 않는다', () => {
    expect(withCode(['A'], 'A')).toEqual(['A']);
    expect(withCode(['A'], 'B')).toEqual(['A', 'B']);
  });

  it('뺄 수 있다', () => {
    expect(withoutCode(['A', 'B'], 'A')).toEqual(['B']);
  });
});
