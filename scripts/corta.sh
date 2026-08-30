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
source "$(dirname "$(readlink -f "$0")")/lib.sh"

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

# Converte HH:MM:SS.mmm (ou MM:SS.mmm, ou segundos) para segundos.
#
# Era aritmética inteira do bash ($((10#$s))), que só aceitava segundo
# cheio e estourava em qualquer valor com casa decimal. Segundo cheio não
# serve: o ponto de corte vem da transcrição, e a fronteira de palavra cai
# em qualquer lugar — cortar em 61s em vez de 61,73s parte o "aí" no meio.
# awk faz a conta em ponto flutuante e ainda dispensa o prefixo 10#, que
# existia só para o bash não ler "08" como octal.
to_sec() {
  awk -F: '{ if (NF==3) printf "%.3f", $1*3600+$2*60+$3;
             else if (NF==2) printf "%.3f", $1*60+$2;
             else printf "%.3f", $1 }' <<< "$1"
}

# Uma ENTRADA por trecho, com -ss/-to, concatenadas numa só passagem.
# Continua sem arquivos intermediários e sem reencodes sucessivos.
#
# O erro que isto corrige (30/08/2026): a versão anterior usava um único
# -i e derivava um ramo [0:v]trim=start=..:end=.. por trecho. Reusar a
# mesma entrada em vários ramos faz o ffmpeg inserir um split implícito,
# e o split precisa entregar cada frame decodificado a TODOS os ramos ao
# mesmo tempo — os que o concat ainda não está consumindo acumulam na
# fila do filtro. Em 1080p60 yuv420p cada frame decodificado ocupa
# 3,1 MB; alguns milhares enfileirados passaram de 12 GB numa máquina de
# 15 GB, e o OOM killer levou a IDE junto três vezes. Nada a ver com o
# tamanho do arquivo: o vídeo do teste tinha 5 minutos e 170 MB.
#
# Com um -i por trecho o ffmpeg busca direto no ponto e decodifica só o
# necessário — não existe split, não existe fila. Medido no mesmo corte
# do improviso_2: 12 GB e morte por OOM viraram 1,2 GB estáveis do começo
# ao fim, e a duração da saída (186,95 s) confere com a soma dos trechos
# (186,91 s; a diferença é arredondamento de frame).
#
# O -ss vem ANTES do -i de propósito: como opção de entrada ele busca no
# índice em vez de decodificar e descartar desde o zero. A precisão não
# se perde — com reencode o ffmpeg faz accurate seek por padrão, e o
# ponto de corte continua caindo na fronteira de palavra que o
# words.tsv apontou.
INPUTS=(); ROTULOS=""; N=0
while read -r ini fim; do
  [[ -z "${ini:-}" || "${ini:0:1}" == "#" ]] && continue
  S=$(to_sec "$ini"); E=$(to_sec "$fim")
  INPUTS+=(-ss "$S" -to "$E" -i "$IN")
  ROTULOS+="[${N}:v][${N}:a]"
  N=$((N+1))
done < "$LISTA"

[[ "$N" -gt 0 ]] || { echo "Nenhum trecho válido em $LISTA" >&2; exit 1; }

echo "==> Aplicando $N trecho(s)"

ffmpeg_lim -y -hide_banner -loglevel warning -stats \
  "${INPUTS[@]}" \
  -filter_complex "${ROTULOS}concat=n=${N}:v=1:a=1[outv][outa]" \
  -map "[outv]" -map "[outa]" \
  -c:v libx264 -crf 23 -preset fast -pix_fmt yuv420p \
  -c:a aac -b:a 192k -ar 48000 \
  -metadata:s:a:0 language=por \
  -movflags +faststart \
  "$OUT/${BASE}_final.mp4"

echo
ls -lh "$IN" "$OUT/${BASE}_final.mp4"
echo "Pronto: $OUT/${BASE}_final.mp4"
