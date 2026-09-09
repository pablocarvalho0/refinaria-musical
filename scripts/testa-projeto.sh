#!/usr/bin/env bash
# Confere que as duas implementações de projeto_de concordam.
#
# A regra vive em dois lugares (lib.sh e projeto.py) porque metade do
# pipeline é shell. Duas cópias divergem sozinhas com o tempo — a menos
# que alguma coisa reclame. Isto é essa coisa.
#
# Uso: ./scripts/testa-projeto.sh

set -uo pipefail
RAIZ="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
PY="$RAIZ/.venv/bin/python"
[[ -x "$PY" ]] || PY=python3

TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
export RAIZ_OUT="$TMP/out"
mkdir -p "$RAIZ_OUT"/{ep00,improviso_3,improviso_4}

source "$RAIZ/scripts/lib.sh"

# caminho -> projeto esperado
CASOS=(
  "$HOME/video/inbox/improviso_4.mp4|improviso_4"
  "$HOME/video/inbox/video_0.mp4|video_0"
  "$RAIZ_OUT/improviso_4/improviso_4_v_norm.mp4|improviso_4"
  "$RAIZ_OUT/ep00/ep00.words.tsv|ep00"
  "$HOME/video/work/improviso_4_v.wav|improviso_4"
  "$HOME/video/work/improviso_3_cover_audio.wav|improviso_3"
  "$HOME/video/work/ep00.words.tsv|ep00"
  "$HOME/video/inbox/20260717_113135.mp4|20260717_113135"
  "$HOME/video/out/solto_norm.mp4|solto"
  "relativo/improviso_3.mp4|improviso_3"
  "$HOME/video/out/novo.16x9.ass|novo"
  "$HOME/video/out/novo.9x16.ass|novo"
  "$HOME/video/work/novo.words.tsv|novo"
  "$HOME/video/work/novo.segments.tsv|novo"
  "$HOME/video/out/novo.v3.mp4|novo"
  "$HOME/video/out/novo_audio_final.mp4|novo"
  # dentro de uma rodada de teste: o degrau 2 pega o PRIMEIRO componente,
  # então a profundidade extra não confunde o episódio
  "$RAIZ_OUT/improviso_4/testes/r1/improviso_4_opA.mp4|improviso_4"
  "$RAIZ_OUT/ep00/testes/2026-09-05-x/ep00_norm.mp4|ep00"
)

falhas=0
printf "%-52s %-14s %-14s %s\n" CAMINHO ESPERADO BASH PYTHON
for caso in "${CASOS[@]}"; do
  caminho="${caso%%|*}"; esperado="${caso##*|}"
  b=$(projeto_de "$caminho")
  p=$("$PY" "$RAIZ/scripts/projeto.py" "$caminho")
  marca="ok"
  [[ "$b" == "$esperado" && "$p" == "$esperado" ]] || { marca="FALHOU"; ((falhas++)); }
  printf "%-52s %-14s %-14s %-14s %s\n" \
    "${caminho/#$HOME\//~/}" "$esperado" "$b" "$p" "$marca"
done

# o escape hatch vence tudo
b=$(PROJETO=manual projeto_de "$RAIZ_OUT/ep00/ep00.srt")
p=$(PROJETO=manual "$PY" "$RAIZ/scripts/projeto.py" "$RAIZ_OUT/ep00/ep00.srt")
[[ "$b" == manual && "$p" == manual ]] \
  && echo "PROJETO= sobrepõe: ok" \
  || { echo "PROJETO= sobrepõe: FALHOU ($b / $p)"; ((falhas++)); }

# ---------------------------------------------------------------------
# RODADA: o segundo lugar onde os dois espelhos podem divergir
#
# Não basta concordarem no NOME do projeto — desde 05/09/2026 eles também
# decidem em qual PASTA escrever, e é aí que uma rodada de teste pode
# vazar para cima do entregável sem ninguém ver.
# ---------------------------------------------------------------------
confere() {  # rótulo, esperado, obtido_bash, obtido_python
  if [[ "$3" == "$2" && "$4" == "$2" ]]; then
    echo "$1: ok"
  else
    echo "$1: FALHOU  esperado=$2  bash=$3  python=$4"; ((falhas++))
  fi
}

ALVO="$HOME/video/inbox/improviso_4.mp4"

pasta_projeto "$ALVO"
confere "sem RODADA, escreve na raiz" "$RAIZ_OUT/improviso_4" \
  "$PROJETO_DIR" "$("$PY" "$RAIZ/scripts/projeto.py" --dir "$ALVO")"

RODADA=r1 pasta_projeto "$ALVO"
confere "com RODADA, escreve em testes/" "$RAIZ_OUT/improviso_4/testes/r1" \
  "$PROJETO_DIR" "$(RODADA=r1 "$PY" "$RAIZ/scripts/projeto.py" --dir "$ALVO")"

confere "com RODADA, a raiz do episódio não se move" "$RAIZ_OUT/improviso_4" \
  "$PROJETO_RAIZ" "$(RODADA=r1 "$PY" "$RAIZ/scripts/projeto.py" --episodio "$ALVO")"

# RODADA com barra ou '..' escreveria fora da pasta do episódio
for ruim in "../fuga" "a/b" ""; do
  bash -c "source '$RAIZ/scripts/lib.sh'; RODADA='$ruim' pasta_projeto '$ALVO'; \
           echo \"\$PROJETO_DIR\"" >/dev/null 2>&1
  rb=$?
  RODADA="$ruim" "$PY" "$RAIZ/scripts/projeto.py" --dir "$ALVO" >/dev/null 2>&1
  rp=$?
  esperado=2; [[ -z "$ruim" ]] && esperado=0   # RODADA vazia = sem rodada
  if [[ ( $esperado == 2 && $rb != 0 && $rp != 0 ) || \
        ( $esperado == 0 && $rb == 0 && $rp == 0 ) ]]; then
    echo "RODADA='$ruim' tratada igual nos dois: ok"
  else
    echo "RODADA='$ruim': FALHOU (bash=$rb python=$rp)"; ((falhas++))
  fi
done

echo
if (( falhas )); then echo "$falhas caso(s) divergindo"; exit 1; fi
echo "as duas implementações concordam em ${#CASOS[@]} casos + RODADA"
