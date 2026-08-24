#!/usr/bin/env bash
# Pipeline Fase 0 — v2
#
# Mudança em relação à v1: o auto-editor saiu.
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

IN="${1:?uso: $0 <arquivo.mp4>}"
[[ -f "$IN" ]] || { echo "Arquivo não encontrado: $IN" >&2; exit 1; }

BASE=$(basename "$IN"); BASE="${BASE%.*}"
WORK="$HOME/video/work"
OUT="$HOME/video/out"
mkdir -p "$WORK" "$OUT"

# Parâmetros ajustáveis via variável de ambiente
CRF="${CRF:-23}"        # 18=quase sem perda, 23=padrão, 28=pequeno
PRESET="${PRESET:-fast}"
LUFS="${LUFS:--14}"     # -14 é o alvo do YouTube

echo "==> Fonte: $IN"
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
#    loudnorm        normaliza volume para o alvo do YouTube
#    -ar 48000       o loudnorm opera a 192 kHz internamente e vaza taxa
#                    dobrada (96 kHz) se a saida nao for fixada
#    +faststart      move o índice para o começo do arquivo:
#                    upload e streaming começam sem baixar tudo
# ---------------------------------------------------------------
echo "==> 1/2  Normalizando (1080p60, x264 crf=$CRF, audio $LUFS LUFS)"
time ffmpeg -y -hide_banner -loglevel warning -stats \
  -hwaccel cuda -i "$IN" \
  -vf "scale=1920:1080" -r 60 \
  -c:v libx264 -crf "$CRF" -preset "$PRESET" -pix_fmt yuv420p \
  -af "loudnorm=I=${LUFS}:TP=-1.5:LRA=11" \
  -c:a aac -b:a 192k -ar 48000 \
  -movflags +faststart \
  "$OUT/${BASE}_norm.mp4"

# ---------------------------------------------------------------
# 2. Áudio para transcrição
#    16 kHz mono é o formato nativo do Whisper. Extraído do arquivo
#    normalizado para os timestamps baterem com o vídeo de trabalho.
# ---------------------------------------------------------------
echo
echo "==> 2/2  Extraindo audio para transcricao"
ffmpeg -y -hide_banner -loglevel error \
  -i "$OUT/${BASE}_norm.mp4" \
  -vn -ac 1 -ar 16000 \
  "$WORK/${BASE}.wav"

echo
echo "-----------------------------------------------"
ls -lh "$IN" "$OUT/${BASE}_norm.mp4"
echo
echo "Proximo passo:"
echo "  ~/video/scripts/transcreve.sh $WORK/${BASE}.wav"
echo
echo "Depois cole a transcricao no chat para gerar a lista de cortes."