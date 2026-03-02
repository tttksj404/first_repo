import google.generativeai as genai
import sys
import os
from datetime import datetime
from dotenv import load_dotenv

# --- Load Environment Variables ---
base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(base_dir, ".env"))

API_KEY = os.getenv("GEMINI_API_KEY")
VAULT_PATH = os.getenv("OBSIDIAN_VAULT_PATH", os.path.expanduser("~/Documents/Obsidian/Learning_Logs"))

if not API_KEY:
    print("❌ GEMINI_API_KEY is not set. Please add it to your .env file.")
    sys.exit(1)

genai.configure(api_key=API_KEY)
model = genai.GenerativeModel('gemini-flash-latest')

def save_to_obsidian(prompt, response_text):
    if not os.path.exists(VAULT_PATH):
        try:
            os.makedirs(VAULT_PATH)
        except Exception as e:
            print(f"❌ Error creating directory {VAULT_PATH}: {e}")
            sys.exit(1)
    
    date_str = datetime.now().strftime("%Y-%m-%d")
    file_path = os.path.join(VAULT_PATH, f"{date_str}.md")
    
    # Use triple-quoted string for multi-line content to avoid f-string issues
    log_content = f"""
### 📝 학습 기록 ({datetime.now().strftime('%H:%M:%S')})
**Q:** {prompt}

**A:** {response_text}

---
"""
    try:
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(log_content)
        print(f"✅ 답변이 옵시디언({date_str}.md)에 저장되었습니다.")
    except Exception as e:
        print(f"❌ Error saving to Obsidian: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용법: gemini \"질문 내용\"")
    else:
        user_prompt = " ".join(sys.argv[1:])
        print("🤖 Gemini가 생각 중입니다...")
        try:
            response = model.generate_content(user_prompt)
            save_to_obsidian(user_prompt, response.text)
        except Exception as e:
            print(f"❌ Error generating response: {e}")
