/** API 주소와 인증 헤더를 한 곳에서 정한다. */
export const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';

// NEXT_PUBLIC_ 값은 빌드 때 번들에 박혀 브라우저로 내려간다. 즉 비밀이 아니다 —
// 웹 화면을 열 수 있는 사람은 이 키도 볼 수 있다. API 포트만 따로 노출됐을 때
// 아무나 직접 두드리지 못하게 하는 용도로만 쓴다.
const KEY = process.env.NEXT_PUBLIC_API_KEY || '';

export function apiHeaders(extra: Record<string, string> = {}): Record<string, string> {
  return KEY ? { ...extra, 'X-API-Key': KEY } : extra;
}
