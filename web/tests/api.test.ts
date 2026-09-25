import { afterEach, describe, expect, it, vi } from 'vitest';

// NEXT_PUBLIC_ 값은 모듈이 읽힐 때 고정되므로 매번 새로 불러온다.
async function load(env: Record<string, string | undefined>) {
  vi.resetModules();
  for (const [k, v] of Object.entries(env)) vi.stubEnv(k, v as string);
  return import('../lib/api');
}

afterEach(() => vi.unstubAllEnvs());

describe('apiHeaders', () => {
  it('키가 없으면 헤더를 더하지 않는다', async () => {
    const { apiHeaders } = await load({ NEXT_PUBLIC_API_KEY: '' });
    expect(apiHeaders({ 'Content-Type': 'application/json' })).toEqual({
      'Content-Type': 'application/json',
    });
  });

  it('키가 있으면 X-API-Key를 싣는다', async () => {
    const { apiHeaders } = await load({ NEXT_PUBLIC_API_KEY: 's3cret' });
    expect(apiHeaders({ 'Content-Type': 'application/json' })).toEqual({
      'Content-Type': 'application/json',
      'X-API-Key': 's3cret',
    });
  });

  it('API 주소 기본값은 localhost:8080', async () => {
    const { API } = await load({ NEXT_PUBLIC_API_URL: '' });
    expect(API).toBe('http://localhost:8080');
  });
});
