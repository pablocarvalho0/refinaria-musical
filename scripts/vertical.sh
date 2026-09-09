#!/usr/bin/env bash
# Master horizontal -> entregável vertical 9:16, por EMPILHAMENTO.
#
# Existe porque o improviso_4 é uma gravação de duas pessoas num plano aberto
# 16:9, e nenhum corte 9:16 cabe as duas. Medido no frame de t=40s:
#
#   corte central 9:16   -> não pega ninguém: sobra parede e um prato de bateria
#   banda + fundo borrado-> pega as duas, mas a imagem útil ocupa 32% da altura
#                           e o resto é borrão preto em cima, laranja embaixo
#   EMPILHADO            -> as duas em tamanho grande, tela cheia, sem borrão
#
# O empilhado corta duas metades do quadro e as põe uma sobre a outra. Só é
# possível porque a fonte é 8K: cada painel vem de um recorte de 3840x3413,
# ou seja, ainda é redução, não ampliação.
#
# A RESOLUÇÃO DE SAÍDA É CALCULADA, não escrita. Ver `resolucao_vertical`
# abaixo: o script escolhe o maior degrau 9:16 que o master sustente sem
# ampliar em NENHUMA etapa. Master 8K entrega 2160x3840; master 4K com plano
# fechado entrega 1080x1920, porque a janela mais apertada não dá mais que
# isso. RESOLUCAO=1080|1440|2160 força, como ORIENTACAO= força a orientação.
#
# A saída segue o contrato do processa.sh: vídeo pronto, áudio COPIADO (cru),
# mais o .wav de 16 kHz da transcrição. Quem trata áudio é o audio.sh, sozinho.
#
# Uso:
#   ./scripts/vertical.sh inbox/improviso_4.mp4 --sufixo v \
#       [--topo-y 600] [--base-y 150] [--troca] [--geral 7.2]
#
#   --topo-y / --base-y  deslocamento vertical de cada recorte, em px do master.
#                        É por onde se corrige cabeça cortada: são os únicos
#                        dois números que dependem de como a câmera ficou.
#   --troca              inverte quem vai em cima.
#   --fechado SEGUNDOS   abre em PLANO FECHADO — o 9:16 mais apertado que o
#                        master permite, tela cheia — e depois AFASTA até o
#                        plano geral. Exige --geral. O centro horizontal do
#                        recorte e --fechado-x, em pixels do master.
#   --fechado-x PX       onde centrar o plano fechado (padrao: 3/4 da largura)
#   --geral SEGUNDOS     abre com o PLANO GERAL — o quadro inteiro do master
#                        deitado, ajustado à largura — e só então divide a
#                        tela. Sem isso o espectador cai direto no empilhado
#                        e nunca vê a sala: os dois painéis não dizem que
#                        estão no mesmo cômodo, e a divisão parece montagem
#                        de duas gravações separadas. Com os primeiros
#                        segundos em plano geral ela lê como o que é — um
#                        take só, aberto.
#   --volta SEG[:DUR]    no fim, o empilhado se dissolve de VOLTA a VOLTA+DUR
#                        e a imagem VOLTA ao plano geral. Fecha o arco onde
#                        ele abriu, e dá aos créditos o quadro inteiro. Exige
#                        --geral. DUR cai no dobro da transição se omitido:
#                        a divisão é um evento, a volta é um repouso, e
#                        repouso lento não lê como corte.
#   --destaque T0:T1[:X] entre T0 e T1 a tela inteira vira a janela 9:16 mais
#                        apertada que o master permite, centrada em X (px do
#                        master), com fundido de alfa nas duas pontas. Serve
#                        para dar o quadro inteiro a quem está conduzindo o
#                        trecho. Repetível.
#
# Os instantes de --geral, --fechado, --volta e --destaque querem cair no
# tempo forte da música: transição fora da batida briga com ela, em cima
# dela some dentro dela. Quem mede é scripts/grade-musical.py --encaixa.
#
# ZOOM= e TRANSICAO= no ambiente sobrepõem os tokens de mesmo nome, para
# experimentar um tempo sem editar marca/tokens.toml. O valor que vencer na
# tela vai para os tokens — o ambiente é rascunho, não fonte da verdade.

set -euo pipefail
source "$(dirname "$(readlink -f "$0")")/lib.sh"

IN=""; SUFIXO="v"; TOPO_Y=600; BASE_Y=150; TROCA=0; GERAL=""; CRF="${CRF:-20}"
FECHADO=""; FECHADO_X=""; VOLTA=""; VOLTA_DUR=""; DESTAQUE=()
ZOOM_AMB="${ZOOM:-}"   # guardado antes de o token preencher a variável
PRESET="${PRESET:-fast}"
RAIZ="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
PY_TOKENS="${PY_TOKENS:-python3}"

while (( $# )); do
  case "$1" in
    --sufixo) SUFIXO="$2"; shift 2 ;;
    --topo-y) TOPO_Y="$2"; shift 2 ;;
    --base-y) BASE_Y="$2"; shift 2 ;;
    --troca)  TROCA=1; shift ;;
    --geral)  GERAL="$2"; shift 2 ;;
    --fechado)   FECHADO="$2"; shift 2 ;;
    --fechado-x) FECHADO_X="$2"; shift 2 ;;
    --volta)     IFS=: read -r VOLTA VOLTA_DUR <<<"$2"; shift 2 ;;
    --destaque)  DESTAQUE+=("$2"); shift 2 ;;
    -*) echo "opção desconhecida: $1" >&2; exit 2 ;;
    *)  IN="$1"; shift ;;
  esac
done

[[ -n "$IN" && -f "$IN" ]] || { echo "uso: $0 <master.mp4> [--sufixo v]" >&2; exit 2; }

BASE=$(basename "$IN"); BASE="${BASE%.*}${SUFIXO:+_$SUFIXO}"
WORK="$HOME/video/work"
# O projeto sai do MASTER, não do BASE: o --sufixo distingue a entrega
# dentro da pasta, não cria pasta nova. improviso_4 --sufixo v escreve em
# out/improviso_4/improviso_4_v_norm.mp4.
pasta_projeto "$IN"
OUT="$PROJETO_DIR"
mkdir -p "$WORK"
projeto_resumo

geometria_video "$IN"
geometria_resumo
[[ -z "$FECHADO" || -n "$GERAL" ]] || {
  echo "--fechado precisa de --geral: o plano fechado AFASTA para o geral," >&2
  echo "e sem o geral não há para onde afastar" >&2; exit 2; }
[[ -z "$VOLTA" || -n "$GERAL" ]] || {
  echo "--volta precisa de --geral: sem plano geral não há para onde voltar" >&2
  exit 2; }
[[ "$GEO_ORIENT" == horizontal ]] || {
  echo "este script empilha DUAS metades de um plano horizontal;" >&2
  echo "o master já é vertical — use o processa.sh" >&2; exit 1; }

# Cada painel tem 1080x960, proporção 9:8. O recorte no master mantém essa
# proporção por construção: metade da largura, e a altura que fecha 9:8.
# Assim o `scale` seguinte é redução pura — nunca esticão. (Foi exatamente o
# esticão silencioso que derrubou o vertical em 05/09; ver "Orientação do
# master" no CLAUDE.md.)
MEIA=$(( GEO_W / 2 ))
ALT=$(( MEIA * 8 / 9 )); ALT=$(( ALT - ALT % 2 ))
(( ALT <= GEO_H )) || { echo "o master não tem altura para dois painéis 9:8" >&2; exit 1; }

# clampa os deslocamentos: pedir mais do que existe faz o crop falhar no meio
# do encode, depois de minutos de trabalho
(( TOPO_Y + ALT <= GEO_H )) || TOPO_Y=$(( GEO_H - ALT ))
(( BASE_Y + ALT <= GEO_H )) || BASE_Y=$(( GEO_H - ALT ))

if (( TROCA )); then X_TOPO=$MEIA; X_BASE=0; else X_TOPO=0; X_BASE=$MEIA; fi

# ---------------------------------------------------------------------------
# A resolução de saída se decide pela FONTE, não pelo formato.
#
# O 1080x1920 era literal em dez lugares deste script e não era decisão: era
# o número que estava aqui quando ele nasceu. Num master 8K isso descartava
# 94% dos pixels e 4,4x do bitrate — e o modo de falha era mudo, porque o
# encode sai com código 0 e o arquivo toca. Ver "Resolução de entrega" no
# CLAUDE.md.
#
# A regra é uma só: SUBIR ATÉ ONDE TODA ETAPA AINDA FOR REDUÇÃO. Quem manda
# é a etapa mais apertada, e ela não é a mesma em todo episódio:
#
#   empilhado      recorte de METADE da largura  -> teto = GEO_W/2
#   fechado/destaque  janela 9:16 = GEO_H*9/16   -> teto = essa janela
#
# Num 8K com plano fechado a janela dá 2430 px, e o maior degrau que cabe é
# 2160. Num 4K a mesma janela dá 1215, e só cabe 1080. Sem plano fechado o
# 4K subiria a 1440 — por isso o teto olha as etapas que a execução usa, não
# as que o script sabe fazer.
DEGRAUS=(1080 1440 2160 2880 4320)
TETO=$MEIA
LIMITANTE="empilhado (metade da largura do master)"
if [[ -n "$FECHADO" || ${#DESTAQUE[@]} -gt 0 ]]; then
  JANELA_9X16=$(( GEO_H * 9 / 16 ))
  if (( JANELA_9X16 < TETO )); then
    TETO=$JANELA_9X16
    LIMITANTE="janela 9:16 mais apertada (plano fechado/destaque)"
  fi
fi

if [[ -n "${RESOLUCAO:-}" ]]; then
  SAI_W="$RESOLUCAO"
  echo "==> Resolução: ${SAI_W} forçada por RESOLUCAO= (teto calculado: ${TETO})"
  (( SAI_W <= TETO )) || echo "    AVISO: acima do teto — vai AMPLIAR em ${LIMITANTE}" >&2
else
  SAI_W=0
  for d in "${DEGRAUS[@]}"; do (( d <= TETO )) && SAI_W=$d; done
  (( SAI_W > 0 )) || {
    echo "o master é pequeno demais: nem 1080 de largura cabe sem ampliar" >&2
    echo "  teto ${TETO} px, limitado por ${LIMITANTE}" >&2; exit 1; }
fi
SAI_H=$(( SAI_W * 16 / 9 )); SAI_H=$(( SAI_H - SAI_H % 2 ))
SAI_MEIA_H=$(( SAI_H / 2 ))
SAI_MEIO_X=$(( SAI_W / 2 ))
echo "==> Saída: ${SAI_W}x${SAI_H}  (teto ${TETO} px por ${LIMITANTE})"

FPS_MASTER=$(ffprobe -v error -select_streams v:0 -show_entries stream=r_frame_rate \
             -of default=nw=1:nk=1 "$IN" | awk -F/ '{printf "%.6f", $1/($2?$2:1)}')
DUR_MASTER=$(ffprobe -v error -show_entries format=duration \
             -of default=nw=1:nk=1 "$IN")
CMDS="$WORK/${BASE}.zoom.cmds"

echo "==> Empilhado: dois recortes de ${MEIA}x${ALT} -> ${SAI_W}x${SAI_MEIA_H} cada"
echo "    topo : x=${X_TOPO} y=${TOPO_Y}"
echo "    base : x=${X_BASE} y=${BASE_Y}"

# O `split` aqui é seguro, ao contrário do que derrubou a IDE em 30/08: o
# vstack consome os dois ramos em travamento, um frame de cada por vez, então
# nenhuma fila cresce. O que estourava era `trim`+`concat`, em que um ramo
# ficava minutos esperando o outro ser drenado. Mesmo assim vai pelo
# ffmpeg_lim: frame 8K decodificado ocupa ~50 MB, e a margem aqui é fina.
RAMOS=2; ROTULOS="[a][b]"
[[ -n "$GERAL" ]] && { RAMOS=$((RAMOS + 1)); ROTULOS+="[w]"; }
for ((i = 1; i <= ${#DESTAQUE[@]}; i++)); do
  RAMOS=$((RAMOS + 1)); ROTULOS+="[e${i}]"
done
VF="[0:v]split=${RAMOS}${ROTULOS};"
VF+="[a]crop=${MEIA}:${ALT}:${X_TOPO}:${TOPO_Y},scale=${SAI_W}:${SAI_MEIA_H}[t];"
VF+="[b]crop=${MEIA}:${ALT}:${X_BASE}:${BASE_Y},scale=${SAI_W}:${SAI_MEIA_H}[d];"
VF+="[t][d]vstack=inputs=2,setsar=1"

if [[ -n "$GERAL" ]]; then
  # A duração do fundido vem dos tokens: onde e como o quadro se divide é
  # apresentação, e apresentação não mora dentro de script.
  TR="${TRANSICAO:-$("$PY_TOKENS" -c "
import pathlib, tomllib
with (pathlib.Path('$RAIZ') / 'marca' / 'tokens.toml').open('rb') as f:
    print(tomllib.load(f)['empilhado']['transicao'])")}"
  [[ -n "${TRANSICAO:-}" ]] && echo "    (TRANSICAO=${TR}s do ambiente sobrepoe o token)"
  echo "    geral: quadro inteiro ate ${GERAL}s, divide em ${TR}s de fundido"

  # O empilhado e composto POR CIMA do plano geral, com o alfa subindo. Nao e
  # xfade de proposito: o xfade precisa segurar um dos lados em buffer, e aqui
  # os dois ramos saem do mesmo `split` — e a receita da fila que estourou a
  # memoria em 30/08. Com overlay + fade de alfa, o `overlay` drena os dois
  # ramos em travamento, um frame de cada, e nada se acumula.
  VF+=",format=rgba,fade=t=in:st=${GERAL}:d=${TR}:alpha=1"

  # A VOLTA e o mesmo mecanismo ao contrario: o alfa do empilhado desce e o
  # plano geral, que nunca deixou de existir por baixo, reaparece. Nao ha
  # ramo novo nem buffer — e a razao de o fundido ser de alfa desde o inicio.
  FIM_ST=$("$PY_TOKENS" -c "print(f'{float('$DUR_MASTER') + 1:.3f}')")
  if [[ -n "$VOLTA" ]]; then
    VOLTA_DUR="${VOLTA_DUR:-$("$PY_TOKENS" -c "print(f'{float('$TR') * 2:.3f}')")}"
    FIM_ST=$("$PY_TOKENS" -c "print(f'{float('$VOLTA') + float('$VOLTA_DUR'):.3f}')")
    (( $(echo "$VOLTA > $GERAL" | bc -l) )) || {
      echo "--volta ($VOLTA s) precisa vir depois de --geral ($GERAL s)" >&2
      exit 2; }
    echo "    volta: empilhado se dissolve em ${VOLTA}s, ${VOLTA_DUR}s de fundido"
    VF+=",fade=t=out:st=${VOLTA}:d=${VOLTA_DUR}:alpha=1"
  fi
  VF+="[st];"

  if [[ -n "$FECHADO" ]]; then
    # ---------------------------------------------------------------
    # Plano fechado que AFASTA para o geral.
    #
    # A janela mais apertada que existe num 9:16 de master deitado usa a
    # altura inteira: largura = altura * 9/16. Mais fechado que isso só
    # ampliando, e ampliar 8K já reduzido não devolve detalhe nenhum.
    #
    # O truque é não animar o recorte, e sim a ESCALA: o master é reduzido
    # a uma largura que encolhe de W1 (quando a janela de saída cobre só
    # o trecho fechado) até SAI_W (quando o quadro inteiro cabe na tela), e
    # o `overlay` recentra sozinho porque a expressão dele lê `overlay_w`.
    # Assim cada frame é uma redução direta do 8K — nunca uma ampliação de
    # algo já reduzido. Ver scripts/zoom-cmds.py para o porquê de sendcmd.
    # ---------------------------------------------------------------
    ZOOM="${ZOOM:-$("$PY_TOKENS" -c "
import pathlib, tomllib
with (pathlib.Path('$RAIZ') / 'marca' / 'tokens.toml').open('rb') as f:
    print(tomllib.load(f)['empilhado']['zoom'])")}"
    [[ -n "${ZOOM_AMB:-}" ]] && echo "    (ZOOM=${ZOOM}s do ambiente sobrepoe o token)"

    read -r W1 H1 FX1 JANELA FECHADO_X < <("$PY_TOKENS" -c "
gw, gh = $GEO_W, $GEO_H
janela = round(gh * 9 / 16)                 # a janela 9:16 mais apertada
cx = ${FECHADO_X:-0} or round(gw * 3 / 4)   # centro do fechado, em px do master
cx = min(max(cx, janela // 2), gw - janela // 2)
w1 = round(gw * $SAI_W / janela / 2) * 2    # largura do master quando fechado
h1 = round(w1 * gh / gw / 2) * 2
print(w1, h1, cx / gw, janela, cx)")

    (( $(echo "$FECHADO < $GERAL" | bc -l) )) || {
      echo "--fechado ($FECHADO s) precisa acabar antes de --geral ($GERAL s)" >&2
      exit 2; }

    echo "    fechado: janela de ${JANELA}px centrada em x=${FECHADO_X}, ate ${FECHADO}s"
    "$PY_TOKENS" "$RAIZ/scripts/zoom-cmds.py" --inicio "$FECHADO" \
      --duracao "$ZOOM" --fps "$FPS_MASTER" --de "$W1" --para "$SAI_W" \
      --proporcao "$(awk -v a=$GEO_H -v b=$GEO_W 'BEGIN{printf "%.6f", a/b}')" \
      --saida "$CMDS"

    # x: o ponto da imagem que fica no centro da tela vai de FX1 (a fracao
    # da largura onde esta o assunto) a 0,5 (o centro do quadro), em sincronia
    # com a propria largura — nao com o relogio. Assim o recentramento nao
    # tem como sair de fase com a escala.
    XE="${SAI_MEIO_X}-(${FX1}-((${W1}-overlay_w)/(${W1}-${SAI_W}))*(${FX1}-0.5))*overlay_w"
    VF+="[w]sendcmd=f=${CMDS},scale@z=${W1}:${H1},setsar=1[img];"
    VF+="[1:v][img]overlay=x='${XE}':y='${SAI_MEIA_H}-overlay_h/2':eval=frame:shortest=1[wide];"
  else
    # o plano geral: o master deitado ajustado a largura, centrado, tarja preta
    # em cima e embaixo. force_original_aspect_ratio=decrease + pad e a mesma
    # defesa do lib.sh — o alvo e exato, mas nada e esticado para chegar la.
    VF+="[w]scale=${SAI_W}:${SAI_H}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
    VF+="pad=${SAI_W}:${SAI_H}:(ow-iw)/2:(oh-ih)/2,setsar=1[wide];"
  fi

  VF+="[wide][st]overlay=0:0:format=auto:enable='between(t,${GERAL},${FIM_ST})'[base];"
else
  VF+="[base];"
fi

# ---------------------------------------------------------------------------
# Destaques: a tela inteira vira a janela 9:16 mais apertada do master,
# centrada em quem está conduzindo o trecho.
#
# Cada destaque é um ramo próprio do `split`, sobreposto por alfa como o
# empilhado — mesmo motivo, mesma segurança: o `overlay` drena os ramos em
# travamento e nenhuma fila cresce. O recorte é 2430x4320 num master 8K, ou
# seja, ainda redução; num master menor a conta muda e o script avisa.
# ---------------------------------------------------------------------------
CADEIA="[base]"
for ((i = 1; i <= ${#DESTAQUE[@]}; i++)); do
  IFS=: read -r DT0 DT1 DX <<<"${DESTAQUE[$((i - 1))]}"
  [[ -n "${DT1:-}" ]] || { echo "--destaque quer T0:T1[:X]" >&2; exit 2; }
  DFADE="${TR:-0.5}"
  read -r JW JX DSAI < <("$PY_TOKENS" -c "
gw, gh = $GEO_W, $GEO_H
jw = round(gh * 9 / 16 / 2) * 2
if jw > gw:
    raise SystemExit('o master nao tem largura para uma janela 9:16')
cx = ${DX:-0} or round(gw * 3 / 4)
x = min(max(cx - jw // 2, 0), gw - jw)
print(jw, x, f'{max(float('$DT0'), float('$DT1') - float('$DFADE')):.3f}')")
  echo "    destaque ${i}: janela de ${JW}px em x=${JX}, ${DT0}s -> ${DT1}s"
  VF+="[e${i}]crop=${JW}:${GEO_H}:${JX}:0,scale=${SAI_W}:${SAI_H},setsar=1,format=rgba,"
  VF+="fade=t=in:st=${DT0}:d=${DFADE}:alpha=1,"
  VF+="fade=t=out:st=${DSAI}:d=${DFADE}:alpha=1[dq${i}];"
  VF+="${CADEIA}[dq${i}]overlay=0:0:format=auto:enable='between(t,${DT0},${DT1})'[b${i}];"
  CADEIA="[b${i}]"
done
VF+="${CADEIA}format=yuv420p[v]"

ACOD=$(ffprobe -v error -select_streams a:0 -show_entries stream=codec_name -of csv=p=0 "$IN")
ASR=$(ffprobe -v error -select_streams a:0 -show_entries stream=sample_rate -of csv=p=0 "$IN")
if [[ "$ACOD" == "aac" && "$ASR" == "48000" ]]; then
  AUDIO=(-c:a copy); echo "==> Audio: $ACOD $ASR Hz — copiado sem reencodar"
else
  AUDIO=(-c:a aac -b:a 192k -ar 48000); echo "==> Audio: $ACOD $ASR Hz — reencodando"
fi

if [[ "${SECO:-0}" == "1" ]]; then
  echo; echo "==> SECO=1: nada renderizado. Filtro:"; echo "$VF" | tr ';' '\n'; exit 0
fi

echo
echo "==> 1/2  Encode (${SAI_W}x${SAI_H}@60, x264 crf=$CRF)"
time ffmpeg_lim -y -hide_banner -loglevel warning -stats \
  -hwaccel cuda -i "$IN" \
  ${FECHADO:+-f lavfi -t $(awk -v d="$DUR_MASTER" 'BEGIN{printf "%.3f", d+1}') \
    -i color=c=black:s=${SAI_W}x${SAI_H}:r=${FPS_MASTER}} \
  -filter_complex "$VF" -map "[v]" -map 0:a \
  -r 60 -c:v libx264 -crf "$CRF" -preset "$PRESET" -pix_fmt yuv420p \
  "${AUDIO[@]}" -metadata:s:a:0 language=por \
  -movflags +faststart \
  "$OUT/${BASE}_norm.mp4"

echo
echo "==> 2/2  Audio de 16 kHz para a transcricao"
ffmpeg -y -hide_banner -loglevel error -i "$OUT/${BASE}_norm.mp4" \
  -vn -af "aresample=16000:async=1:first_pts=0" -ac 1 "$WORK/${BASE}.wav"

echo
ls -lh "$OUT/${BASE}_norm.mp4"
ffprobe -v error -select_streams v:0 \
  -show_entries stream=width,height,r_frame_rate,nb_frames,pix_fmt,sample_aspect_ratio \
  -of default=nw=1 "$OUT/${BASE}_norm.mp4"
