#!/usr/bin/env bash
# Wrapper de transcrição — ponto de entrada oficial.
#
# Existe por causa de um detalhe do linker: o CTranslate2 carrega
# cuBLAS/cuDNN preguiçosamente e não olha dentro do venv. Construir o
# WhisperModel não falha; a falha aparece só na primeira inferência, como
#   RuntimeError: Library libcublas.so.12 is not found
#
# O linker dinâmico lê LD_LIBRARY_PATH no boot do processo — mudar a
# variável depois, de dentro do Python, não tem efeito. Por isso ela é
# exportada aqui, antes do interpretador subir.
#
# Uso: ./transcreve.sh ~/video/work/20260824_135542.wav [--model medium]

set -euo pipefail

ROOT="$HOME/video"
VENV="$ROOT/.venv"

[[ -x "$VENV/bin/python" ]] || {
  echo "venv não encontrado em $VENV" >&2
  echo "criar com: python3 -m venv $VENV" >&2
  exit 1
}

PY="$VENV/bin/python"

# Caminho das libs CUDA empacotadas pelos wheels nvidia-*.
# O pacote 'nvidia' é namespace package: __file__ é None, usar __path__[0].
if NV=$("$PY" -c "import nvidia; print(nvidia.__path__[0])" 2>/dev/null); then
  export LD_LIBRARY_PATH="$NV/cublas/lib:$NV/cudnn/lib:${LD_LIBRARY_PATH:-}"
else
  echo "aviso: wheels CUDA da nvidia não encontrados no venv — vai cair para CPU" >&2
fi

exec "$PY" "$ROOT/scripts/transcreve.py" "$@"
