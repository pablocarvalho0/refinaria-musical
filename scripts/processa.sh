#!/usr/bin/env bash
# Pipeline Fase 0 — corte de silêncio + normalização de áudio + extração p/ transcrição
# Uso: ./processa.sh ~/video/inbox/20260824_135542.mp4

set -euo pipefail

IN="${1:?uso: $0 <arquivo.mp4>}"
[[ -f "$IN" ]] || { echo "Arquivo não encontrado: $IN" >&2; exit 1; }

BASE=$(basename "$IN"); BASE="${BASE%.*}"
WORK="$HOME/video/work"
OUT="$HOME/video/out"
mkdir -p "$WORK" "$OUT"

echo "==> Fonte: $IN"
ffprobe -v error -show_entries format=duration:stream=width,height,r_frame_rate \
        -of default=noprint_wrappers=1 "$IN"

# ---------------------------------------------------------------
# 1. Corte de silêncio
#    Trabalha no arquivo original. --margin preserva 0.3s antes e
#    depois de cada trecho com fala, senão o corte come o início
#    das palavras.
# ---------------------------------------------------------------
echo "==> 1/3  Cortando silêncio"
auto-editor "$IN" \
  --margin 0.3sec \
  --no-open \
  -o "$WORK/${BASE}_cut.mp4"

# ---------------------------------------------------------------
# 2. Normalização de áudio + reencode do vídeo
#    loudnorm alvo -14 LUFS (padrão YouTube).
#    NVENC na GPU; se falhar, cai pro libx264 no CPU.
# ---------------------------------------------------------------
echo "==> 2/3  Normalizando áudio e reencodando"
if ! ffmpeg -y -hide_banner -loglevel warning -stats \
      -hwaccel cuda -i "$WORK/${BASE}_cut.mp4" \
      -af "loudnorm=I=-14:TP=-1.5:LRA=11" \
      -c:v h264_nvenc -preset p5 -rc vbr -cq 23 -b:v 0 \
      -c:a aac -b:a 192k \
      "$OUT/${BASE}_final.mp4"; then
  echo "    NVENC falhou — refazendo no CPU"
  ffmpeg -y -hide_banner -loglevel warning -stats \
      -i "$WORK/${BASE}_cut.mp4" \
      -af "loudnorm=I=-14:TP=-1.5:LRA=11" \
      -c:v libx264 -crf 23 -preset veryfast \
      -c:a aac -b:a 192k \
      "$OUT/${BASE}_final.mp4"
fi

# ---------------------------------------------------------------
# 3. Áudio para transcrição
#    Extraído do vídeo JÁ CORTADO, para os timestamps baterem
#    com o que vai ao ar. 16 kHz mono é o que o Whisper espera.
# ---------------------------------------------------------------
echo "==> 3/3  Extraindo áudio"
ffmpeg -y -hide_banner -loglevel error \
  -i "$OUT/${BASE}_final.mp4" \
  -vn -ac 1 -ar 16000 \
  "$WORK/${BASE}.wav"

echo
echo "Vídeo:  $OUT/${BASE}_final.mp4"
echo "Áudio:  $WORK/${BASE}.wav"
ls -lh "$IN" "$OUT/${BASE}_final.mp4"
echo
echo "Próximo: python ~/video/scripts/transcreve.py $WORK/${BASE}.wav"