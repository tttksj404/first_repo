import os.path
import json
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# 권한 범위: 문서 생성 및 수정을 위한 권한
SCOPES = ['https://www.googleapis.com/auth/documents', 'https://www.googleapis.com/auth/drive.file']

def get_credentials():
    creds = None
    # 이전에 인증한 토큰이 있으면 로드
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    
    # 인증이 만료되었거나 없으면 새로 인증
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        
        # 다음 실행을 위해 토큰 저장
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return creds

def create_doc():
    creds = get_credentials()

    try:
        service = build('docs', 'v1', credentials=creds)

        # 1. 문서 제목 설정 및 생성
        title = '[2026] LEET 고득점(140+) 정복을 위한 SSAFY 병행 마스터 플랜'
        doc = service.documents().create(body={'title': title}).execute()
        document_id = doc.get('documentId')
        print(f"✅ 문서 생성 완료! ID: {document_id}")
        print(f"🔗 링크: https://docs.google.com/document/d/{document_id}/edit")

        # 2. 본문 내용 구성
        content_text = (
            "1. 월별 로드맵
"
            "3월: 2017~2025 기출 해부 및 논리 기초
"
            "4월: 취약 유형 정복 및 PSAT 병행
"
            "5월: 입법고시 기출 등 고난도 적응
"
            "6월: 실전 시뮬레이션 및 시간 관리
"
            "7월: 파이널 정리 및 컨디션 관리

"
            "2. 데일리 루틴
"
            "08:30-09:00: 아침 예열 (언어 1지문)
"
            "13:10-13:45: 점심 틈새 (추리 퀴즈)
"
            "20:15/40-23:00: 저녁 집중 학습 및 논리 분석 기록

"
            "3. 논리 피드백 기록 가이드
"
            "기록처: Google Docs (본 문서 하단 또는 별도 문서)
"
            "양식: [문제 출처 / 나의 오답 논리 / 정답의 필연성 / 향후 행동 강령]
"
        )

        # 3. 문서에 텍스트 삽입 요청 (Batch Update)
        requests = [
            {
                'insertText': {
                    'location': {'index': 1},
                    'text': content_text
                }
            }
        ]

        service.documents().batchUpdate(documentId=document_id, body={'requests': requests}).execute()
        print("✨ 플랜 데이터 업로드 성공!")

    except HttpError as err:
        print(f"❌ 오류 발생: {err}")

if __name__ == '__main__':
    create_doc()
