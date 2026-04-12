#!/bin/bash
# 전수 조합 앙상블 3모델 토론 실행
# GPT-5.4 (codex) + Gemini 3.1 Pro (gemini) + Claude Opus (합의)
#
# 사용법: ./scripts/run_ensemble_3model_debate.sh
# 결과: quant_runtime/output/ensemble_3model_debate.json

set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

echo "=== 3모델 토론: 전수 조합 앙상블 백테스트 ==="
echo "  Step 1: GPT-5.4 (codex) 독립 평가"
echo "  Step 2: Gemini 3.1 Pro 독립 평가"
echo "  Step 3: Claude Opus 합의 도출"
echo ""

python3 "04. Tools/agent-stack/dot_studio_bridge/scripts/run_sequence.py" \
  --spec-file scripts/ensemble_3model_debate.json \
  --pretty \
  | tee quant_runtime/output/ensemble_3model_debate.json

echo ""
echo "=== 결과 저장: quant_runtime/output/ensemble_3model_debate.json ==="
