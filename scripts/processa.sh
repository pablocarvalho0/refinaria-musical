#!/usr/bin/env bash
# Pipeline Fase 0 — v3
#
# Mudança em relação à v2: este script não toca mais no áudio.
#
# Antes ele aplicava loudnorm de passo único ao arquivo inteiro. Medido:
# isso movimenta o ganho em 9,09 dB ao longo da região musical (achata o
# violão), erra o alvo em 1,25 dB, e deixa a fala 2,9 dB abaixo da música.
# O tratamento de áudio agora é responsabilidade exclusiva do audio.sh,
# que separa fala de música e mede antes de aplicar.
#
# Aqui o áudio é COPIADO sem reencodar. Três consequências:
#   - zero geração de perda: o _audio.mp4 final tem uma geração de AAC,
#     não duas;
#   - o áudio do _norm.mp4 é bit-idêntico ao do master, então não existe
#     mais defasagem entre a linha do tempo da transcrição e a do audio.sh
#     (eram 21,33 ms — 1024 samples, o atraso do codificador AAC);
#   - o encode fica um pouco mais rápido.
#
# O _norm.mp4 continua assistível para escolher os cortes, mas com os
# níveis crus: no ep00 a música fica a -8,83 LUFS e a fala a -14,97.
# Ele NÃO é entregável. O entregável de áudio é o _audio.mp4.
#
# Mudança da v1 para a v2: o auto-editor saiu.
# Motivo: corte por energia de áudio não distingue pausa de fala (lixo)
# de pausa musical (conteúdo). Num vídeo de violão ele corta justamente
# onde não deve, e devolveu só 2% de redução no teste. O corte agora é
# semântico, feito a partir da transcrição, num passo separado.
#
# Resultado: um único reencode em vez de três. Menos perda de geração,
# menos tempo, arquivo menor.
#
# Uso: ./processa.sh ~/video/inbox/20260824_135542.mp4

set -euo pipefail
source "$(dirname "$(readlink -f "$0")")/lib.sh"

IN="${1:?uso: $0 <arquivo.mp4>}"
[[ -f "$IN" ]] || { echo "Arquivo não encontrado: $IN" >&2; exit 1; }

BASE=$(basename "$IN"); BASE="${BASE%.*}"
WORK="$HOME/video/work"
# A saída é por projeto: out/<projeto>/. Um master gera várias entregas
# (vertical, cover, variantes de cartela) e o nome do arquivo era a única
# coisa separando uma da outra. Ver "Pasta de saída por projeto" no lib.sh.
pasta_projeto "$IN"
OUT="$PROJETO_DIR"
mkdir -p "$WORK"

# Parâmetros ajustáveis via variável de ambiente
CRF="${CRF:-23}"        # 18=quase sem perda, 23=padrão, 28=pequeno
PRESET="${PRESET:-fast}"

echo "==> Fonte: $IN"
projeto_resumo
ffprobe -v error -show_entries format=duration:stream=width,height,codec_name \
        -of default=noprint_wrappers=1 "$IN"
echo

# ---------------------------------------------------------------
# 1. Encode único: 4K HEVC -> 1080p H.264 + áudio normalizado
#
#    -hwaccel cuda   decodifica HEVC na GPU (a parte cara)
#    libx264         encoda no CPU: 4x menor que o NVENC no mesmo
#                    CRF, medido nos nossos testes
#    -r 60           força CFR; o Android grava VFR, que causa
#                    dessincronia de áudio ao longo da edição
#    -vf $GEO_VF     alvo 1920x1080 ou 1080x1920 conforme a orientação
#                    do master (ver geometria_video no lib.sh). Era um
#                    scale fixo em 16:9, que esmagava vertical calado
#    -c:a copy       o áudio passa intacto; quem trata é o audio.sh
#    +faststart      move o índice para o começo do arquivo:
#                    upload e streaming começam sem baixar tudo
# ---------------------------------------------------------------

# O celular grava AAC 48 kHz estéreo, que entra no MP4 sem conversão.
# Fonte diferente cai no reencode — sem loudnorm, só para caber no
# container. Vale checar em vez de supor: copiar um codec incompatível
# faz o ffmpeg falhar no fim do encode, depois de 2 minutos de trabalho.
ACOD=$(ffprobe -v error -select_streams a:0 \
       -show_entries stream=codec_name -of csv=p=0 "$IN")
ASR=$(ffprobe -v error -select_streams a:0 \
      -show_entries stream=sample_rate -of csv=p=0 "$IN")
if [[ "$ACOD" == "aac" && "$ASR" == "48000" ]]; then
  AUDIO=(-c:a copy)
  echo "==> Audio: $ACOD $ASR Hz — copiado sem reencodar"
else
  AUDIO=(-c:a aac -b:a 192k -ar 48000)
  echo "==> Audio: $ACOD $ASR Hz — reencodando para AAC 48 kHz (sem loudnorm)"
fi

# A orientação sai do master, não de um valor fixo: o canal produz
# horizontal (YouTube longo) e vertical (Shorts e Reels), e a diferença
# entre os dois é invisível em width/height — está no side data rotation.
geometria_video "$IN"
geometria_resumo
echo

echo "==> 1/2  Normalizando video (${GEO_ALVO_W}x${GEO_ALVO_H}@60, x264 crf=$CRF)"
time ffmpeg_lim -y -hide_banner -loglevel warning -stats \
  -hwaccel cuda -i "$IN" \
  -vf "$GEO_VF" -r 60 \
  -c:v libx264 -crf "$CRF" -preset "$PRESET" -pix_fmt yuv420p \
  "${AUDIO[@]}" \
  -metadata:s:a:0 language=por \
  -movflags +faststart \
  "$OUT/${BASE}_norm.mp4"

# ---------------------------------------------------------------
# 2. Áudio para transcrição
#
# 16 kHz mono é o formato nativo do Whisper.
#
# first_pts=0 não é detalhe: o stream de áudio do celular não começa em
# zero (no ep00, em 0,048896 s), e o WAV não tem como guardar esse
# offset — ao escrever o arquivo o ffmpeg simplesmente o descarta. Sem o
# first_pts=0 a transcrição inteira sai adiantada em relação ao vídeo, e
# com ela todo ponto de corte. Medido no _norm da v2: 27 ms, 1,6 frame.
# Com o first_pts=0 o ffmpeg preenche o começo com silêncio e o instante
# t=0 do WAV passa a ser o instante t=0 do vídeo.
# ---------------------------------------------------------------
echo
echo "==> 2/2  Extraindo audio para transcricao"
ffmpeg -y -hide_banner -loglevel error \
  -i "$OUT/${BASE}_norm.mp4" \
  -vn -af "aresample=16000:async=1:first_pts=0" -ac 1 \
  "$WORK/${BASE}.wav"

echo
echo "-----------------------------------------------"
ls -lh "$IN" "$OUT/${BASE}_norm.mp4"
echo
echo "Proximo passo:"
echo "  ~/video/scripts/transcreve.sh $WORK/${BASE}.wav"
echo
echo "Depois cole a transcricao no chat para gerar a lista de cortes."
echo
echo "O audio do _norm.mp4 esta CRU. Para o entregavel:"
echo "  python scripts/segmenta.py $WORK/${BASE}.wav"
echo "  ~/video/scripts/audio.sh $OUT/${BASE}_norm.mp4"