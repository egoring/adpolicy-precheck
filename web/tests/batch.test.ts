import { describe, expect, it } from 'vitest';
import { parseBatch } from '../lib/batch';

describe('parseBatch', () => {
  it('한 줄에 URL 하나, 쉼표 뒤는 광고 문구', () => {
    expect(parseBatch('https://a.example, 업계 1위\nhttps://b.example')).toEqual({
      rows: [
        { url: 'https://a.example', ad_copy: '업계 1위' },
        { url: 'https://b.example', ad_copy: '' },
      ],
      errors: [],
    });
  });

  it('따옴표 안의 쉼표·따옴표는 문구의 일부다 (CSV)', () => {
    const { rows } = parseBatch('"https://a.example","할인, 오늘만 ""특가"""');
    expect(rows).toEqual([{ url: 'https://a.example', ad_copy: '할인, 오늘만 "특가"' }]);
  });

  it('탭으로 나눈 것도 받는다 (스프레드시트 붙여넣기)', () => {
    expect(parseBatch('https://a.example\t문구').rows).toEqual([
      { url: 'https://a.example', ad_copy: '문구' },
    ]);
  });

  it('머리글 줄과 빈 줄은 건너뛴다', () => {
    const { rows } = parseBatch('url,ad_copy\n\nhttps://a.example,x\n');
    expect(rows).toEqual([{ url: 'https://a.example', ad_copy: 'x' }]);
  });

  it('URL이 아닌 줄은 몇 번째 줄인지와 함께 알려준다', () => {
    const { rows, errors } = parseBatch('https://a.example\nexample.com 문구');
    expect(rows).toHaveLength(1);
    expect(errors).toEqual(['2번째 줄: URL은 http:// 또는 https://로 시작해야 합니다']);
  });
});
