import { describe, expect, it } from 'vitest';
import { describeError, describeFailure } from '../lib/errors';

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

describe('describeFailure', () => {
  it('서버가 준 문자열 detail을 그대로 보여준다 (504 안내가 사라지면 안 된다)', async () => {
    const msg = '점검이 180초를 넘겨 중단했습니다. check_images=false로 다시 시도하세요.';
    expect(await describeFailure(json(504, { detail: msg }))).toBe(msg);
  });

  it('검증 오류 배열은 msg만 모아 잇는다', async () => {
    const res = json(422, { detail: [{ msg: 'URL 형식' }, { msg: '너무 김' }, {}] });
    expect(await describeFailure(res)).toBe('URL 형식 · 너무 김');
  });

  it('429의 속도 제한 안내도 detail로 보여준다', async () => {
    const res = json(429, { detail: '점검 요청이 너무 많습니다. 분당 20회까지입니다.' });
    expect(await describeFailure(res)).toContain('분당 20회');
  });

  it('본문 없는 401은 API 키 안내로 바꾼다', async () => {
    expect(await describeFailure(new Response('', { status: 401 }))).toContain('NEXT_PUBLIC_API_KEY');
  });

  it('본문 없는 504는 이미지 점검을 끄라고 안내한다', async () => {
    expect(await describeFailure(new Response('', { status: 504 }))).toContain('이미지 점검');
  });

  it('JSON이 아닌 본문은 상태 코드로 떨어진다', async () => {
    expect(await describeFailure(new Response('<html>bad gateway', { status: 502 }))).toBe('요청 실패 (502)');
  });
});

describe('describeError', () => {
  it('중단은 오류가 아니라 사용자가 한 일이다', () => {
    expect(describeError(new DOMException('aborted', 'AbortError'))).toBe('점검을 중단했습니다.');
  });

  it('fetch의 TypeError는 연결·CORS 확인 안내로 바꾼다', () => {
    const msg = describeError(new TypeError('Failed to fetch'));
    expect(msg).toContain('CORS_ORIGINS');
    expect(msg).not.toContain('Failed to fetch');
  });

  it('그 밖의 Error는 메시지를 그대로', () => {
    expect(describeError(new Error('뭔가 잘못됨'))).toBe('뭔가 잘못됨');
    expect(describeError('문자열')).toBe('알 수 없는 오류');
  });
});
