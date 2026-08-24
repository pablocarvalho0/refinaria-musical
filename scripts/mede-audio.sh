#!/usr/bin/env bash
# Mede loudness de um arquivo, no total e separadamente por classe.
#
# Uso: ./mede-audio.sh <arquivo> [segmentos.txt]
#
# Sem segmentos.txt mede só o arquivo inteiro. Com ele, mede também as
# regiões FALA e MUSICA isoladamente — é aí que se vê se o tratamento
# diferenciado fez alguma coisa, porque a média do arquivo inteiro esconde
# exatamente a diferença que se quer medir.
#
# Reporta LUFS integrado (I), true peak (TP) e loudness range (LRA), lidos
# do primeiro passo do loudnorm, que é um medidor EBU R128 completo.

set -euo pipefail

IN="${1:?uso: $0 <arquivo> [segmentos.txt]}"
SEG="${2:-}"
[[ -f "$IN" ]] || { echo "não encontrado: $IN" >&2; exit 1; }

# Mede um trecho já filtrado. Recebe o filtro de áudio pronto e imprime
# I / TP / LRA. O loudnorm em print_format=json faz a análise R128 e
# escreve o resultado no stderr; -f null descarta o áudio.
medir() {
  local filtro="$1"
  ffmpeg -hide_banner -nostats -i "$IN" \
    -filter_complex "${filtro}loudnorm=print_format=json[m]" \
    -map "[m]" -f null - 2>&1 \
  | awk '/^\{/,/^\}/' \
  | python3 -c '
import json, sys
d = json.load(sys.stdin)
v = [float(d[k]) for k in ("input_i", "input_tp", "input_lra", "input_thresh")]
print("I=%7.2f LUFS   TP=%6.2f dBTP   LRA=%5.2f LU   thresh=%7.2f" % tuple(v))'
}

echo "=== $IN ==="
printf 'TOTAL   '; medir "[0:a]"

[[ -n "$SEG" && -f "$SEG" ]] || exit 0

# Concatena as regiões de uma classe num só fluxo e mede. Sem isso a
# medição diluiria fala e música na mesma média.
por_classe() {
  local classe="$1"
  local filtro n
  filtro=$(awk -v C="$classe" '
    /^#/ || NF < 3 { next }
    $1 == C {
      split($2, a, ":"); s = a[1]*3600 + a[2]*60 + a[3]
      split($3, b, ":"); e = b[1]*3600 + b[2]*60 + b[3]
      printf "[0:a]atrim=start=%.3f:end=%.3f,asetpts=PTS-STARTPTS[c%d];", s, e, n++
    }
    END { for (i = 0; i < n; i++) printf "[c%d]", i; printf "concat=n=%d:v=0:a=1,", n }
  ' "$SEG")
  n=$(awk -v C="$classe" '/^#/ || NF < 3 {next} $1 == C {n++} END {print n+0}' "$SEG")
  [[ "$n" -gt 0 ]] || { printf '%-8s (nenhuma regiao)\n' "$classe"; return; }
  printf '%-8s' "$classe"; medir "$filtro"
}

por_classe FALA
por_classe MUSICA
