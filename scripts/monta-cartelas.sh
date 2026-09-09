#!/usr/bin/env bash
# Sobrepõe uma lista arbitrária de cartelas a um vídeo.
#
# É o irmão genérico do cartelas.sh. Aquele monta a peça de COVER — duas
# cartelas, tempos vindos dos tokens, texto passado por flags nomeadas. Este
# recebe as cartelas já desenhadas, com o instante de cada uma, e não sabe o
# que elas dizem. Existe porque a piada do improviso_4 pede três cartelas em
# duas batidas, e o cartelas.sh só sabe fazer duas.
#
# O áudio é COPIADO, sempre — cartela é trabalho de imagem, e quem produz
# áudio neste projeto é o audio.sh, sozinho.
#
# Uso:
#   ./scripts/monta-cartelas.sh ENTRADA.mp4 SAIDA.mp4 \
#       PNG:entra:sai [PNG:entra:sai ...]
#
#   'sai' pode ser 'fim' — a cartela fica até o fim do vídeo.
#   FADE=0.8 e FADE_VIDEO=1.5 saem de marca/tokens.toml se não vierem do
#   ambiente.

set -euo pipefail
source "$(dirname "$(readlink -f "$0")")/lib.sh"
RAIZ="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
PY="${PY:-python3}"

ENTRADA="${1:?uso: $0 ENTRADA.mp4 SAIDA.mp4 PNG:entra:sai ...}"
SAIDA="${2:?falta a saída}"
shift 2
(( $# )) || { echo "nenhuma cartela informada" >&2; exit 2; }

[[ -f "$ENTRADA" ]] || { echo "não encontrado: $ENTRADA" >&2; exit 1; }

leia_token() { "$PY" - "$RAIZ" "$1" <<'PYEOF'
import sys, pathlib, tomllib
raiz, chave = pathlib.Path(sys.argv[1]), sys.argv[2]
with (raiz / "marca" / "tokens.toml").open("rb") as f:
    print(tomllib.load(f)["cartela"][chave])
PYEOF
}
FADE="${FADE:-$(leia_token fade_entrada)}"
FADE_VIDEO="${FADE_VIDEO:-$(leia_token fade_video_saida)}"

DUR=$(ffprobe -v error -select_streams v:0 -show_entries stream=duration \
      -of default=nw=1:nk=1 "$ENTRADA")
NBF=$(ffprobe -v error -select_streams v:0 -show_entries stream=nb_frames \
      -of default=nw=1:nk=1 "$ENTRADA")
FPS=$(ffprobe -v error -select_streams v:0 -show_entries stream=r_frame_rate \
      -of default=nw=1:nk=1 "$ENTRADA")
DUR_PNG=$("$PY" -c "print(f'{float('$DUR') + 1:.3f}')")
VFS=$("$PY" -c "print(f'{float('$DUR') - float('$FADE_VIDEO'):.3f}')")

echo "==> $(basename "$ENTRADA")  ${DUR}s  ${NBF} frames @ ${FPS}"

ENTRADAS=(-i "$ENTRADA")
FC=""; CADEIA="[0:v]"
i=0
for spec in "$@"; do
  IFS=: read -r png t0 t1 <<<"$spec"
  [[ -f "$png" ]] || { echo "cartela não encontrada: $png" >&2; exit 1; }
  [[ "$t1" == "fim" ]] && t1="$DUR"
  i=$((i + 1))
  # o fade-out começa uma duração de fade antes de sair; se a cartela fica
  # até o fim, não há fade-out — quem apaga é o fade de imagem do vídeo.
  SAI_FADE=$("$PY" -c "print(f'{max(float('$t0'), float('$t1') - float('$FADE')):.3f}')")
  ENTRADAS+=(-loop 1 -framerate "$FPS" -t "$DUR_PNG" -i "$png")
  # `fade ... :alpha=1` é multiplicativo sobre o alfa que já existe, então o
  # degradê do scrim sobrevive em vez de virar um retângulo chapado.
  FC+="[${i}:v]format=rgba,fade=t=in:st=${t0}:d=${FADE}:alpha=1"
  "$PY" -c "import sys; sys.exit(0 if abs(float('$t1') - float('$DUR')) < 0.01 else 1)" \
    || FC+=",fade=t=out:st=${SAI_FADE}:d=${FADE}:alpha=1"
  FC+="[c${i}];"
  FC+="${CADEIA}[c${i}]overlay=0:0:format=auto:enable='between(t,${t0},${t1})'[v${i}];"
  CADEIA="[v${i}]"
  printf "    %-46s %6.2f -> %s\n" "$(basename "$png")" "$t0" "$t1"
done

# o fade de imagem vem DEPOIS de todos os overlays, de propósito: assim ele
# leva a cartela final junto para o preto, em vez de apagar o vídeo e deixar
# o texto boiando.
FC+="${CADEIA}fade=t=out:st=${VFS}:d=${FADE_VIDEO},format=yuv420p,setsar=1[v]"

if [[ "${SECO:-0}" == "1" ]]; then
  echo "==> SECO=1: nada renderizado. Filtro:"; echo "$FC" | tr ';' '\n'; exit 0
fi

mkdir -p "$(dirname "$SAIDA")"
ffmpeg_lim -nostdin -hide_banner -loglevel warning -y \
  "${ENTRADAS[@]}" \
  -filter_complex "$FC" -map "[v]" -map 0:a \
  -c:v libx264 -crf 20 -preset fast -pix_fmt yuv420p -r "$FPS" \
  -frames:v "$NBF" \
  -c:a copy -metadata:s:a:0 language=por \
  -movflags +faststart \
  "$SAIDA"

echo "==> $SAIDA"
ffprobe -v error -select_streams v:0 \
  -show_entries stream=width,height,r_frame_rate,nb_frames,pix_fmt,sample_aspect_ratio \
  -of default=nw=1 "$SAIDA"
