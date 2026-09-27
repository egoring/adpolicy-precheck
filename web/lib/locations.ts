/** 서버 locations 코드 → 화면 라벨 (C-8). 모르는 코드는 그대로 보여준다. */
const LABEL: Record<string, string> = {
  title: '페이지 제목',
  meta_description: '메타 설명',
  link_text: '링크 글자',
  image_alt: '이미지 대체텍스트(alt)',
  form: '입력 폼',
  body: '본문',
  image_text: '이미지 속 글자',
  ad_headline: '광고 제목',
  ad_description: '광고 설명',
  ad_copy: '광고 문구',
};

export function locationLabel(code: string): string {
  if (code.startsWith('mobile:')) {
    return `모바일 ${locationLabel(code.slice('mobile:'.length))}`;
  }
  return LABEL[code] ?? code;
}
