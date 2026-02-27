import os
import re

# 1. 최신 API 키가 저장된 파일 경로
KEY_SOURCE = os.path.join(os.path.dirname(__file__), 'notion_key.txt')
# 2. 업데이트할 대상 폴더 (상위 notion_automation 폴더 전체)
TARGET_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

def sync_keys():
    # 최신 키 읽기
    try:
        with open(KEY_SOURCE, 'r', encoding='utf-8') as f:
            new_key = f.read().strip()
    except FileNotFoundError:
        print(f"❌ 에러: {KEY_SOURCE} 파일이 없습니다. 키를 먼저 작성해주세요.")
        return

    if not new_key:
        print("❌ 에러: 키 파일이 비어 있습니다.")
        return

    print(f"🔄 동기화 시작: 새 키 [{new_key[:10]}...]")
    
    updated_count = 0
    # 모든 .py 파일 탐색
    for root, dirs, files in os.walk(TARGET_DIR):
        for file in files:
            if file.endswith('.py') and file != os.path.basename(__file__):
                file_path = os.path.join(root, file)
                
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()

                    # NOTION_TOKEN = "..." 또는 '...' 패턴 찾기
                    # 따옴표 종류에 상관없이 매칭하도록 수정
                    pattern = r'(NOTION_TOKEN\s*=\s*["\'])(.*?)(["\'])'
                    
                    if re.search(pattern, content):
                        new_content = re.sub(pattern, rf'\1{new_key}\3', content)
                        
                        if content != new_content:
                            with open(file_path, 'w', encoding='utf-8') as f:
                                f.write(new_content)
                            print(f"✅ 업데이트 완료: {file_path}")
                            updated_count += 1
                except Exception as e:
                    print(f"⚠️ {file_path} 처리 중 오류: {e}")

    print(f"\n✨ 작업 완료: 총 {updated_count}개의 파일이 최신 API 키로 동기화되었습니다.")

if __name__ == "__main__":
    sync_keys()
