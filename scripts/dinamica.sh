#!/usr/bin/env bash
# Câmera virtual sobre um master parado: zoom e reenquadramento animados.
#
# Existe porque a gravação do improviso_3 é um plano fixo de 60s — tripé,
# celular, nada se move. O material é bom e o enquadramento é único, e é isso
# que faz o vídeo estacionar na tela por volta dos 20s.
#
# A ideia não é inventar movimento: é usar o que já foi gravado e está sendo
# jogado fora. O master girado é 2160x3840 e o entregável é 1080x1920 — sobra
# um fator 2 inteiro. Enquadrar dentro dele é REDUÇÃO até o zoom 2,00, que é
# recorte 1:1. Acima disso seria ampliar, e o camera.py recusa.
#
# A saída segue o contrato do processa.sh e do vertical.sh: vídeo pronto,
# áudio COPIADO do master. Quem trata áudio neste projeto é o audio.sh (ou o
# violao.sh), sozinho — o áudio daqui existe para o monta-cartelas.sh ter o
# que copiar, e é descartado na junção final.
#
# Uso:
#   ./scripts/dinamica.sh MASTER.mp4 CAMERA.tsv SAIDA.mp4 \
#       [--inicio 41.0] [--duracao 60.700]
#
# O formato do CAMERA.tsv e o porquê de cada filtro estão no scripts/camera.py.
# SECO=1 imprime o filtro e não renderiza.

set -euo pipefail
source "$(dirname "$(readlink -f "$0")")/lib.sh"
RAIZ="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
PY="${PY:-python3}"

IN="${1:?uso: $0 MASTER.mp4 CAMERA.tsv SAIDA.mp4 [--inicio S] [--duracao S]}"
CAM="${2:?falta o TSV de câmera}"
SAIDA="${3:?falta a saída}"
shift 3

INICIO=0
DURACAO=""
while (( $# )); do
  case "$1" in
    --inicio)  INICIO="$2"; shift 2 ;;
    --duracao) DURACAO="$2"; shift 2 ;;
    *) echo "opção desconhecida: $1" >&2; exit 2 ;;
  esac
done

[[ -f "$IN"  ]] || { echo "não encontrado: $IN"  >&2; exit 1; }
[[ -f "$CAM" ]] || { echo "não encontrado: $CAM" >&2; exit 1; }

geometria_video "$IN"

DUR_TOTAL=$(ffprobe -v error -select_streams v:0 -show_entries stream=duration \
            -of default=nw=1:nk=1 "$IN")
FPS_R=$(ffprobe -v error -select_streams v:0 -show_entries stream=r_frame_rate \
        -of default=nw=1:nk=1 "$IN")
FPS=$("$PY" -c "n,d='$FPS_R'.split('/'); print(f'{int(n)/int(d):.6f}')")

[[ -n "$DURACAO" ]] || DURACAO=$("$PY" -c "print(f'{float('$DUR_TOTAL')-float('$INICIO'):.3f}')")
# frames exatos: o -t sozinho deixa a contagem à mercê do arredondamento do
# seek, e contagem desigual quebra concat e overlay três passos depois.
NBF=$("$PY" -c "print(round(float('$DURACAO')*float('$FPS')))")

echo "==> $(basename "$IN")  ${GEO_W}x${GEO_H} girado ${GEO_ROT}°  @ ${FPS} fps"
echo "    trecho: ${INICIO}s + ${DURACAO}s = ${NBF} frames"
echo "    alvo:   ${GEO_ALVO_W}x${GEO_ALVO_H} (${GEO_ORIENT})"

FILTRO=$("$PY" "$RAIZ/scripts/camera.py" "$CAM" \
  --master-w "$GEO_W" --master-h "$GEO_H" \
  --saida-w "$GEO_ALVO_W" --saida-h "$GEO_ALVO_H" \
  --fps "$FPS" --duracao "$DURACAO" --relatorio)

if [[ "${SECO:-0}" == "1" ]]; then
  echo "==> SECO=1: nada renderizado. Filtro:"; echo "$FILTRO"; exit 0
fi

mkdir -p "$(dirname "$SAIDA")"

# -ss antes do -i: além de ser o seek barato, ele rebaseia os timestamps para
# zero, e é disso que as expressões de `t` da câmera dependem. Com -copyts a
# câmera procuraria o primeiro enquadramento em t=41s e o vídeo sairia parado.
#
# hwaccel cuda decodifica o HEVC 4K na GPU, que é a parte cara; o scale por
# frame e o x264 ficam na CPU, como todo o resto do pipeline.
time ffmpeg_lim -nostdin -hide_banner -loglevel warning -stats -y \
  -hwaccel cuda -ss "$INICIO" -i "$IN" \
  -vf "$FILTRO,format=yuv420p,setsar=1" \
  -frames:v "$NBF" \
  -c:v libx264 -crf 20 -preset fast -pix_fmt yuv420p -r "$FPS" \
  -c:a copy -metadata:s:a:0 language=por \
  -movflags +faststart \
  "$SAIDA"

echo "==> $SAIDA"
ffprobe -v error -select_streams v:0 \
  -show_entries stream=width,height,r_frame_rate,nb_frames,pix_fmt,sample_aspect_ratio \
  -of default=nw=1 "$SAIDA"
