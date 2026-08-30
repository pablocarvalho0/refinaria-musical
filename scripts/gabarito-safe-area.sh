#!/usr/bin/env bash
# Gera um vídeo-régua para descobrir, no aplicativo de verdade, que faixa da
# tela a interface do Reels/Shorts cobre.
#
# Por que existe: a margem inferior do formato 9x16 em marca/tokens.toml está
# em 25% da altura, e esse número NÃO foi medido — veio da documentação do
# browser-use/video-use, que usa 31%. É a única peça da identidade visual
# apoiada em fonte secundária, e é justamente a que decide se a legenda fica
# escondida atrás dos botões.
#
# Como medir de verdade:
#   1. ./scripts/gabarito-safe-area.sh
#   2. mande out/gabarito-safe-area.mp4 para o celular
#   3. publique como rascunho no Reels e nos Shorts (não precisa publicar)
#   4. tire um print de cada um
#   5. veja a maior faixa que a interface cobre, embaixo e em cima
#   6. escreva o valor medido em marca/tokens.toml e troque o aviso pelo dado
#
# A régua é rotulada em porcentagem da altura e em pixels, então o print
# responde direto, sem conta.
set -euo pipefail

RAIZ="$(dirname "$(readlink -f "$0")")/.."
cd "$RAIZ"

LARG="${LARG:-1080}"
ALT="${ALT:-1920}"
DUR="${DUR:-8}"
FONTE="${FONTE:-Inter}"
SAIDA="out/gabarito-safe-area.mp4"

# O % literal dentro do drawtext. Aspas SIMPLES de propósito: o texto precisa
# chegar ao filtro como \% depois de o bash e o parser do filtergraph terem
# comido uma barra cada um. Escrito direto entre aspas duplas, o % sobra
# sozinho, o drawtext avisa "Stray %" e descarta o rótulo inteiro — em
# silêncio, porque é warning e não erro. A primeira versão deste gabarito saiu
# com todas as réguas sem legenda por causa disso.
PCT='\\%' 

mkdir -p out

# Régua: uma linha a cada 5%, de baixo para cima até 40%, e do topo até 20%.
# As faixas de baixo alternam de cor para o print ficar legível mesmo
# comprimido pelo aplicativo.
filtros="drawgrid=w=${LARG}:h=$((ALT/20)):t=1:c=white@0.12"

for p in 5 10 15 20 25 30 35 40; do
  y=$(awk -v a="$ALT" -v p="$p" 'BEGIN{printf "%d", a - a*p/100}')
  cor="red@0.85"; esp=3
  # 25% é onde a legenda está hoje; 31% é o que o video-use recomenda
  [ "$p" = 25 ] && { cor="yellow@0.95"; esp=7; }
  [ "$p" = 30 ] && { cor="orange@0.95"; esp=5; }
  filtros="${filtros},drawbox=x=0:y=${y}:w=${LARG}:h=${esp}:color=${cor}:t=fill"
  filtros="${filtros},drawtext=font='${FONTE}':text='${p}${PCT} — ${y}px do topo':\
x=24:y=${y}+14:fontsize=40:fontcolor=white:box=1:boxcolor=black@0.75:boxborderw=8"
done

for p in 5 10 15 20; do
  y=$(awk -v a="$ALT" -v p="$p" 'BEGIN{printf "%d", a*p/100}')
  filtros="${filtros},drawbox=x=0:y=${y}:w=${LARG}:h=3:color=cyan@0.85:t=fill"
  filtros="${filtros},drawtext=font='${FONTE}':text='topo ${p}${PCT}':\
x=24:y=${y}-56:fontsize=40:fontcolor=white:box=1:boxcolor=black@0.75:boxborderw=8"
done

# Uma linha de legenda de mentira, exatamente onde a real vai cair, para o
# print mostrar se ela sobrevive à interface.
MARGEM=480
filtros="${filtros},drawtext=font='${FONTE}':\
text='aqui fica a legenda':\
x=(w-text_w)/2:y=h-${MARGEM}-52:fontsize=78:fontcolor=white:\
borderw=5:bordercolor=black"

filtros="${filtros},drawtext=font='${FONTE}':text='GABARITO — ${LARG}x${ALT}':\
x=(w-text_w)/2:y=h/2:fontsize=54:fontcolor=white@0.55"

echo "==> $SAIDA  (${LARG}x${ALT}, ${DUR}s)"
ffmpeg -nostdin -y -hide_banner -loglevel error \
  -f lavfi -i "color=c=0x3A3A46:s=${LARG}x${ALT}:d=${DUR}:r=30" \
  -f lavfi -i "anullsrc=channel_layout=stereo:sample_rate=48000" \
  -vf "$filtros" -shortest \
  -c:v libx264 -crf 20 -preset medium -pix_fmt yuv420p \
  -c:a aac -b:a 128k -movflags +faststart "$SAIDA"

echo
echo "Linha amarela = 25%, a margem que marca/tokens.toml usa hoje."
echo "Linha laranja = 30%, o limite que o video-use recomenda."
echo
echo "Publique como rascunho no Reels e no Shorts, tire print dos dois e veja"
echo "até que porcentagem a interface cobre. Depois corrija margem_inferior"
echo "em marca/tokens.toml e troque o aviso pelo número medido."
