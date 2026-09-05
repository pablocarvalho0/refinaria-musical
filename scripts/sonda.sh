#!/usr/bin/env bash
# Geometria dos arquivos do inbox, antes de processar.
#
# Existe porque a orientação de um vídeo é invisível na listagem: dois
# arquivos que o ffprobe declara 3840x2160 podem ser um deitado e outro
# em pé, e a diferença mora no side data 'rotation'. Rodar isto antes do
# processa.sh evita descobrir a orientação errada depois de dois minutos
# de encode.
#
# Uso: ./sonda.sh                    # tudo que está no inbox
#      ./sonda.sh arquivo.mp4 ...    # arquivos específicos

set -euo pipefail
source "$(dirname "$(readlink -f "$0")")/lib.sh"

if (( $# )); then
  arquivos=("$@")
else
  mapfile -t arquivos < <(find "$HOME/video/inbox" -maxdepth 1 -type f \
                          \( -iname '*.mp4' -o -iname '*.mov' -o -iname '*.mkv' \) | sort)
fi

(( ${#arquivos[@]} )) || { echo "nada para sondar"; exit 0; }

printf "%-26s %11s %5s %-11s %9s %7s %s\n" \
       ARQUIVO EXIBIDO ROT ORIENTACAO ALVO DURACAO TAMANHO
for f in "${arquivos[@]}"; do
  [[ -f "$f" ]] || { printf "%-26s  (não encontrado)\n" "$(basename "$f")"; continue; }
  geometria_video "$f" || continue
  dur=$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$f" \
        | cut -d. -f1)
  printf "%-26s %11s %4s° %-11s %9s %6ss %s\n" \
    "$(basename "$f")" "${GEO_W}x${GEO_H}" "$GEO_ROT" "$GEO_ORIENT" \
    "${GEO_ALVO_W}x${GEO_ALVO_H}" "${dur:-?}" "$(du -h "$f" | cut -f1)"
done
