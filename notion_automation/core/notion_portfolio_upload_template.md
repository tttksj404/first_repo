# Notion Portfolio Upload Template

이 파일은 Notion API 또는 수동 붙여넣기로 바로 업로드할 수 있게 만든 포트폴리오 작성 템플릿이다.

사용 방법:
1. 아래 각 섹션 내용을 실제 프로젝트 기준으로 채운다.
2. Notion 연동이 복구되면 이 파일 내용을 page/block 단위로 업로드한다.
3. 또는 수동으로 복붙해도 된다.

---

# [프로젝트 제목]

## 1. 프로젝트 개요
- 프로젝트 목적:
- 해결하려던 문제:
- 사용 환경/도메인:
- 기간:

## 2. 내가 한 일
- 
- 
- 

## 3. 기술 포인트
- 핵심 기술:
- 사용 언어/도구:
- 아키텍처/운영 포인트:
- 디버깅/검증 포인트:

## 4. 성과 / 결과
- 실제로 개선된 점:
- 해결한 병목:
- 측정 가능한 변화:
- 아직 남은 한계:

## 5. 한 줄 요약
> 

## 6. 이력서용 버전
- 

## 7. README / GitHub 소개 버전
- 

## 8. 면접 STAR 버전
### Situation
- 

### Task
- 

### Action
- 

### Result
- 

---

# 데이터/AI 직무 맞춤 포트폴리오 템플릿

## 프로젝트명
[예: 실시간 자동매매 시스템 안정화 및 거래소 전환]

## 문제 정의
- 어떤 데이터/시스템/운영 문제가 있었는가?
- 왜 이 문제가 중요한가?

## 접근 방식
- 어떤 로그/데이터/지표를 봤는가?
- 어떤 가설을 세웠는가?
- 어떤 실험/검증 방식을 사용했는가?

## 구현 및 개선 사항
- 데이터 수집/처리 개선:
- 모델/전략/규칙 개선:
- 실행 시스템/운영 안정성 개선:
- 자동화/실험 루프 설계:

## 결과
- 무엇이 실제로 좋아졌는가?
- 어떤 의사결정 품질이 높아졌는가?
- 무엇이 아직 미완료인가?

## 배운 점
- 
- 
- 

## 대표 요약 문장
> Python 기반 실시간 시스템에서 데이터/이벤트 흐름, 실행 안정성, 자산 인식, 전략 실험 자동화를 묶어 운영 가능한 구조로 개선했다.

---

# 현재 프로젝트에 바로 넣을 수 있는 초안 섹션

## AI 기반 자동매매 시스템 디버깅 및 안정화
### 개요
실시간 자동매매 프로그램의 실행 불안정, 주문 실패, 의사결정 루프 정지 문제를 분석하고 수정했다.

### 내가 한 일
- 실시간 daemon이 중간에 죽는 원인 추적
- bootstrap 이후 decision loop가 멈추는 문제 수정
- 주문 실패 시 프로세스가 종료되지 않도록 예외 처리 보강
- heartbeat, decision, live/test order 로그를 기반으로 런타임 상태 검증
- 잔고/최소주문금액/주문 포맷 불일치 문제 추적

### 기술 포인트
- Python 런타임 디버깅
- 실시간 websocket/daemon 구조 분석
- 에러 로그 기반 root cause 분석
- 안전한 주문 실행 경로 설계

### 성과
- 프로세스 생존성 개선
- decision loop 문제 일부 해결
- 실주문 경로 병목을 단계별로 좁힘

## Binance 중심 구조를 Bitget 거래소 구조로 전환
### 개요
기존 Binance 중심 자동매매 코드를 Bitget 거래소에 맞게 전환하는 구조 작업을 진행했다.

### 내가 한 일
- Binance 종속 지점 전수 파악
- Bitget REST client 추가
- exchange abstraction / client factory 추가
- Bitget websocket market-data translation 구현
- Bitget env readiness 및 credential path 정리
- Bitget live daemon wiring 연결
- Bitget용 테스트 추가

### 기술 포인트
- 거래소 API 마이그레이션
- REST/WebSocket 인터페이스 추상화
- 실시간 시장데이터 포맷 변환
- 거래소별 order/account endpoint 적응

### 성과
- Bitget live daemon이 실제로 시작 가능한 수준까지 연결
- Bitget env readiness 정상화
- Bitget market-data path 동작 확인

## 선물 주문 실행 경로 개선 및 자본 인식 보강
### 개요
선물 거래가 실제로 체결되지 않는 문제를 줄이기 위해 주문 포맷, 최소 notional, 잔고 기반 캡핑 로직을 보강했다.

### 내가 한 일
- futures order 400 에러 raw body 재현
- unilateral / one-way position mode 관련 주문 포맷 추적
- Bitget kline granularity mismatch 해결
- futures executionAvailableBalance / crossedMaxAvailable 반영
- USDT 중심 자본 계산을 더 현실적인 execution cap 구조로 보강
- spot/futures 자산 인식 개선 방향 설계 및 일부 반영

### 기술 포인트
- 거래소 에러 코드 해석
- 실거래 주문 payload 디버깅
- 실행 가능 잔고와 총자산 분리
- 레버리지/증거금/최소주문금액 연계 로직

### 성과
- 주문 포맷 문제를 여러 단계로 축소
- 실 live futures path에서 남은 병목을 balance/size 수준까지 좁힘

## 전략 튜닝 자동화(Quant AutoResearch) 워크플로 설계
### 개요
수동 감으로 전략을 바꾸는 대신, replay/paper 기반으로 파라미터를 비교하는 자동 튜닝 워크플로를 설계했다.

### 내가 한 일
- quant-autoresearch 로컬 스킬 설계
- profile별 baseline 실험 자동화
- futures 활성화 / bearish short bias / leverage 강화 variant 비교
- fixture 한계 분석 및 richer fixture 필요성 도출

### 기술 포인트
- 실험 자동화 설계
- 전략 파라미터 비교
- evidence-based optimization
- overfitting 방지 관점의 실험 루프 설계

### 성과
- 전략 자동 튜닝 프레임워크 초안 구축
- 실험 데이터 부족이 병목이라는 점을 명확히 식별

## 운영 보조용 로컬 AI 스킬 설계
### 개요
장기 작업/디버깅/보안 점검/진행 추적을 더 잘하기 위해 로컬 스킬을 직접 설계했다.

### 추가한 스킬
- debug-log-summarizer
- code-review-checkpoint
- work-progress-tracker
- agency-reality-check
- agency-orchestrator-lite
- agency-security-sanity
- agency-exec-summary
- agency-project-ops
- quant-autoresearch

### 기술 포인트
- 작업 자동화
- role-based prompting
- 운영 관점의 AI 보조 체계 설계

### 성과
- 자연어 요청 기반으로 적절한 작업 방식/검증 흐름을 유도하는 기반 구축

## 민감정보 흔적 탐지 및 보안 정리
### 개요
로컬 머신에 남아 있던 거래소/API 관련 흔적을 점검하고 정리했다.

### 내가 한 일
- VS Code history에서 Binance API 흔적 탐지
- Chrome 저장 로그인 흔적 확인
- 민감 흔적 삭제
- 키 노출 가능성에 따른 폐기 권고

### 기술 포인트
- 로컬 credential trace audit
- 개발 환경 보안 점검
- 최소 노출 원칙
