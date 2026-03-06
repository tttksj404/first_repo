# 금융 프로필 프로젝트 구현 원리 설명서

이 문서는 `finance_profile` 프로젝트가 어떤 원리로 만들어졌는지, 처음 보는 사람도 이해할 수 있게 순서대로 설명한 자료입니다.

---

## 1. 프로젝트 전체 구조

### 파일 역할
- `index.html`: 기본 정보 수정 페이지 (F301, F302 중심)
- `portfolio.html`: 포트폴리오 수정 페이지 (F304 중심)
- `style.css`: 두 페이지에 공통 적용되는 디자인/레이아웃/반응형 규칙 (F305)
- `README.md`: 요구사항 대응과 실행 방법 문서 (NF301)

### 페이지가 연결되는 방식
- 두 HTML 파일은 같은 폴더에 있고, 서로 `href="./index.html"`, `href="./portfolio.html"`로 이동합니다.
- 즉, 라우터나 서버 없이도 "정적 페이지 간 이동"이 가능합니다.

---

## 2. `index.html` 구현 원리 (기본 정보 수정 페이지)

## 2-1. 문서 시작과 기본 설정
```html
<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="stylesheet" href="./style.css">
</head>
```
- `<!DOCTYPE html>`: 브라우저가 표준 HTML 모드로 해석하게 합니다.
- `lang="ko"`: 문서 언어가 한국어임을 명시합니다.
- `meta viewport`: 모바일에서 화면 축소/확대 깨짐 없이 반응형이 동작하게 합니다.
- `link rel="stylesheet"`: 공통 스타일 파일을 연결합니다.

## 2-2. 상단 네비게이션 (F303)
```html
<header class="topbar">
  <h1>...</h1>
  <nav>
    <a class="nav-link active" href="./index.html">기본 정보 수정</a>
    <a class="nav-link" href="./portfolio.html">포트폴리오 수정</a>
  </nav>
</header>
```
- `header.topbar`: 상단 고정 영역 역할.
- `nav` 안의 `a`: 페이지 이동 링크.
- 현재 페이지에만 `active` 클래스를 붙여 "지금 어디 있는지" 시각적으로 강조합니다.

## 2-3. 프로필 영역 3분할 레이아웃 (F301)
```html
<section class="card profile-layout">
  <div class="profile-photo-section">...</div>
  <div class="bio-section">...</div>
  <div class="invest-section">...</div>
</section>
```
- `profile-layout`을 CSS Grid 3열로 만들어
  1) 프로필 사진
  2) 자기소개
  3) 투자성향
  을 한 줄에 배치합니다.

### 프로필 사진
```html
<img class="avatar" src="..." alt="회원 프로필 사진">
```
- `alt`: 이미지 로딩 실패/스크린리더 대응 텍스트.
- CSS에서 `border-radius: 50%`로 원형 프로필을 만듭니다.

### 자기소개
```html
<textarea id="intro" rows="7" ...></textarea>
<button type="button" class="btn-primary">자기소개 저장</button>
```
- `textarea`: 여러 줄 텍스트 입력.
- 버튼은 현재 JS 연결 없이 UI만 구성했습니다.

### 투자 성향
- `select`: 위험 선호도 1개 선택.
- `checkbox`: 금융상품 복수 선택.
- `radio`: 투자 스타일 단일 선택.
- 이렇게 input 타입을 나눠 "한 개만 고르는 항목/여러 개 고르는 항목"을 구분했습니다.

## 2-4. 회원 기본 정보 폼 (F302)
```html
<form class="form-grid">
  <input type="text" value="1000234" readonly>
  <input type="text" value="ssafy_user15" readonly>
  <input type="email" ...>
  <input type="text" ...>
  <input type="number" ...>
</form>
```
- `readonly`: 회원번호/ID는 표시만 하고 수정 불가.
- `type="email"`: 이메일 형식 검증 도움.
- `type="number"`: 숫자 입력 중심 제약.
- `form-grid` 클래스로 2열 폼 배치.

---

## 3. `portfolio.html` 구현 원리 (포트폴리오 수정 페이지, F304)

구조는 최대한 `index.html`과 동일하게 유지해 사용자 혼란을 줄였습니다.

### 핵심 폼 항목
- 회원 번호 (`readonly`)
- ID (`readonly`)
- 대출 성향 (`select`)
- 목표 대출액 (`number`)

### 왜 이렇게 구성했는가
- 요구사항의 필드 구성을 그대로 반영.
- 같은 CSS(`form-grid`, `card`, `btn-primary`)를 재사용해 유지보수성을 높임.

---

## 4. `style.css` 구현 원리

## 4-1. 디자인 토큰(변수) 선언
```css
:root {
  --bg: #f3f7ff;
  --card-bg: #ffffff;
  --line: #d8e1ef;
  --text: #1a2a40;
  --primary: #0a6ff2;
}
```
- 색상을 변수로 관리해 한 곳에서 전체 톤 수정이 가능.
- 일관된 UI 색상 체계를 유지할 수 있습니다.

## 4-2. 공통 레이아웃
- `body`: 배경 그라데이션, 기본 폰트, 기본 글자색.
- `.page`: 콘텐츠 최대 폭 제한 + 중앙 정렬.
- `.card`: 흰 배경 카드, 테두리, 라운드.
- `.topbar`: `display: flex`로 제목/네비를 가로 정렬.

## 4-3. 폼 UI 통일
```css
textarea, input, select { ... }
textarea:focus, input:focus, select:focus { ... }
```
- 입력 컴포넌트 모양을 동일하게 맞춤.
- `:focus`에 파란 외곽 효과를 줘 현재 입력 위치를 명확히 표시.

## 4-4. 읽기 전용 필드 구분
```css
input[readonly] {
  background: #f2f5fa;
  color: #5f6f86;
}
```
- 사용자가 "수정 불가 필드"임을 직관적으로 구분할 수 있게 함.

## 4-5. 반응형 핵심 (F305)
```css
@media (max-width: 767px) {
  .profile-layout { grid-template-columns: 1fr; }
  .form-grid { grid-template-columns: 1fr; }
}
```
- 768px 미만에서 3열/2열 레이아웃을 1열로 변경.
- 모바일 화면에서도 항목이 겹치지 않고 세로로 자연스럽게 읽히게 합니다.

---

## 5. 요구사항 번호와 실제 구현 매핑

- F301: `index.html`의 `profile-layout` 섹션 (프로필 사진/자기소개/투자성향)
- F302: `index.html`의 회원 기본 정보 `form`
- F303: 두 페이지 공통 `header > nav`
- F304: `portfolio.html`의 포트폴리오 수정 폼
- F305: `style.css`의 `@media (max-width: 767px)` 규칙
- NF301: `README.md` + 본 설명 문서

---

## 6. 실행 후 직접 확인하는 체크리스트

1. `index.html` 열기
2. 상단 `포트폴리오 수정` 클릭 시 `portfolio.html`로 이동 확인
3. `portfolio.html`에서 `기본 정보 수정` 클릭 시 복귀 확인
4. 창 너비를 768px 아래로 줄여
   - 프로필 3열이 1열로 바뀌는지
   - 폼 2열이 1열로 바뀌는지
   확인

---

## 7. 다음 단계(원하면 확장 가능)

- JavaScript 연결로 "저장" 버튼 클릭 시 유효성 검사/알림 추가
- Bootstrap 컴포넌트 기반으로 동일 화면 재구현
- 더미 데이터 대신 API 연동 형태로 확장
