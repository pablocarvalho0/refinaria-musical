#!/usr/bin/env bash
# Aplica cortes semânticos a partir de uma lista de trechos a MANTER.
#
# Uso:
#   ./corta.sh <video_norm.mp4> <cortes.txt>
#
# Formato do cortes.txt — um intervalo por linha, "início fim":
#   00:00:04  00:01:32
#   00:01:47  00:03:05
#
# Linhas em branco e linhas começando com # são ignoradas.
# O reencode é feito uma vez só, no final, para não empilhar gerações.

set -euo pipefail

IN="${1:?uso: $0 <video.mp4> <cortes.txt>}"
LISTA="${2:?uso: $0 <video.mp4> <cortes.txt>}"
[[ -f "$IN" ]] || { echo "Vídeo não encontrado: $IN" >&2; exit 1; }
[[ -f "$LISTA" ]] || { echo "Lista não encontrada: $LISTA" >&2; exit 1; }

BASE=$(basename "$IN"); BASE="${BASE%.*}"
# Tira o sufixo do passo anterior para não acumular: o corte de um
# _norm.mp4 sai como _final.mp4, não _norm_final.mp4. Só o _norm é
# removido — tirar o _final também faria a saída colidir com a entrada
# ao reaplicar um corte, e o ffmpeg sobrescreveria o próprio fonte.
BASE="${BASE%_norm}"
OUT="$HOME/video/out"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# Converte HH:MM:SS (ou MM:SS, ou segundos) para segundos
to_sec() {
  local t="$1"
  case "$(grep -o ':' <<< "$t" | wc -l)" in
    2) IFS=: read -r h m s <<< "$t"; echo "$((10#$h * 3600 + 10#$m * 60 + 10#$s))" ;;
    1) IFS=: read -r m s <<< "$t";   echo "$((10#$m * 60 + 10#$s))" ;;
    *) echo "$t" ;;
  esac
}

# Monta um filtro único com todos os trechos: corta e concatena numa
# só passagem do ffmpeg. Evita arquivos intermediários e reencodes
# sucessivos.
V=""; A=""; N=0
while read -r ini fim; do
  [[ -z "${ini:-}" || "${ini:0:1}" == "#" ]] && continue
  S=$(to_sec "$ini"); E=$(to_sec "$fim")
  V+="[0:v]trim=start=${S}:end=${E},setpts=PTS-STARTPTS[v${N}];"
  A+="[0:a]atrim=start=${S}:end=${E},asetpts=PTS-STARTPTS[a${N}];"
  N=$((N+1))
done < "$LISTA"

[[ "$N" -gt 0 ]] || { echo "Nenhum trecho válido em $LISTA" >&2; exit 1; }

CONCAT=""
for ((i=0; i<N; i++)); do CONCAT+="[v${i}][a${i}]"; done
CONCAT+="concat=n=${N}:v=1:a=1[outv][outa]"

printf '%s\n%s\n' "$V$A$CONCAT" > "$TMP/filtro.txt"
echo "==> Aplicando $N trecho(s)"

ffmpeg -y -hide_banner -loglevel warning -stats \
  -i "$IN" \
  -filter_complex_script "$TMP/filtro.txt" \
  -map "[outv]" -map "[outa]" \
  -c:v libx264 -crf 23 -preset fast -pix_fmt yuv420p \
  -c:a aac -b:a 192k -ar 48000 \
  -metadata:s:a:0 language=por \
  -movflags +faststart \
  "$OUT/${BASE}_final.mp4"

echo
ls -lh "$IN" "$OUT/${BASE}_final.mp4"
echo "Pronto: $OUT/${BASE}_final.mp4"