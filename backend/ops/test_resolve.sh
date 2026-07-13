#!/bin/bash
cd /mnt/c/synapse-city/backend/training
PY=/root/proprietary-model/.venv/bin/python
R() { $PY -c "import sys; sys.path.insert(0,'.'); from evalsuite.run_suite import _resolve_ollama; print(_resolve_ollama())"; }
echo "env UNSET   -> $(unset SYNAPSE_OLLAMA_URL; R)"
echo "env BROKEN  -> $(SYNAPSE_OLLAMA_URL='http://:11434' R)"
echo "env EMPTY   -> $(SYNAPSE_OLLAMA_URL='' R)"
echo "env GOOD    -> $(SYNAPSE_OLLAMA_URL='http://172.25.144.1:11434' R)"
URL=$(unset SYNAPSE_OLLAMA_URL; R)
curl -s -m 8 "$URL/api/tags" >/dev/null && echo "REACHES OLLAMA via resolved URL: $URL" || echo "UNREACHABLE: $URL"
