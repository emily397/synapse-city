#!/bin/bash
# Re-run ONLY the eval-gate for a given resident+gen, with full error surfacing,
# to isolate the "incumbent unreachable" failure from the training chain.
#   bash rerun_gate.sh <resident> <gen> <incumbent> <adapter:sft|dpo>
set -e
RES="${1:-quinn}"; GEN="${2:-9}"; INC="${3:-qwen2.5:7b-instruct}"; ADAPTER="${4:-dpo}"
WINIP=$(ip route show default | awk '{print $3}')
cd /mnt/c/synapse-city/backend/training
export SYNAPSE_OLLAMA_URL=http://${WINIP}:11434
export SYNAPSE_RESIDENT="$RES"
export SYNAPSE_GATE_TASKS=32
echo "WINIP=$WINIP  RES=$RES GEN=$GEN INC=$INC"
echo "direct WSL->Windows ollama load test:"
curl -s -m 60 -X POST http://${WINIP}:11434/api/generate \
  -d "{\"model\":\"$INC\",\"prompt\":\"say OK\",\"stream\":false}" | head -c 120
echo ""
echo "--- running gate ---"
/root/proprietary-model/.venv/bin/python eval_gate.py \
  --gen "$GEN" --adapter "$ADAPTER" --incumbent "$INC" --suite suite_v2.jsonl
