#!/usr/bin/env bash
# Mixa duas gravações da mesma música aplicando um deslocamento medido.
#
#   ./scripts/mixa-alinhado.sh REFERENCIA OUTRA OFFSET_MS [PREFIXO_SAIDA]
#
# OFFSET_MS é quanto a segunda faixa precisa ser ATRASADA, medido antes por
#   python scripts/alinha-faixas.py ref.wav outra.wav
# Negativo atrasa a referência em vez da outra.
#
# Gera três arquivos ao lado, em out/:
#   _sync.m4a          mix normalizado a -14 LUFS, para ouvir e publicar
#   _sync_dinamico.m4a mix com ganho estático até -1 dBTP, dinâmica intacta
#   _conferencia_LR.m4a referência à esquerda, outra à direita — é assim que
#                       se julga o sincronismo de ouvido, com os dois separados
set -euo pipefail
source "$(dirname "$(readlink -f "$0")")/lib.sh"

[[ $# -ge 3 ]] || { sed -n '2,16p' "$0" | sed 's/^# \?//'; exit 1; }
REF=$1; OUTRA=$2; OFF_MS=$3
PREFIXO=${4:-$(dirname "$REF")/out/$(basename "${REF%.*}")}
mkdir -p "$(dirname "$PREFIXO")" "$(dirname "$REF")/work"
WORK=$(dirname "$REF")/work

# adelay não aceita valor negativo: offset negativo vira atraso na referência
AMOSTRAS=$(python3 -c "print(abs(round($OFF_MS*48))) ")
if (( $(python3 -c "print(1 if $OFF_MS>=0 else 0)") )); then
  DLY_REF=0;         DLY_OUTRA=$AMOSTRAS
else
  DLY_REF=$AMOSTRAS; DLY_OUTRA=0
fi

# Loudness de cada faixa, para entrarem no mix no mesmo nível. O headroom de
# -10/-6 dB existe para a soma não estourar antes da normalização final.
medir_i() { ffmpeg -hide_banner -nostats -i "$1" -af ebur128 -f null - 2>&1 \
            | sed -n '/Summary/,$p' | grep -m1 'I:' | grep -oE '\-?[0-9]+\.[0-9]+'; }
I_REF=$(medir_i "$REF"); I_OUT=$(medir_i "$OUTRA")
G_REF=$(python3 -c "print(f'{-10:.2f}')")
G_OUT=$(python3 -c "print(f'{-10 + ($I_REF) - ($I_OUT):.2f}')")
echo "loudness: referência ${I_REF} LUFS, outra ${I_OUT} LUFS"
echo "ganhos no mix: referência ${G_REF} dB, outra ${G_OUT} dB"
echo "atraso: referência ${DLY_REF} amostras, outra ${DLY_OUTRA} amostras"

FMT="aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=mono"

echo "--> mix cru"
ffmpeg_lim -hide_banner -nostats -v warning -y -i "$REF" -i "$OUTRA" -filter_complex \
"[0:a]${FMT},adelay=${DLY_REF}S:all=1,volume=${G_REF}dB[a];
 [1:a]${FMT},adelay=${DLY_OUTRA}S:all=1,volume=${G_OUT}dB[b];
 [a][b]amix=inputs=2:duration=longest:normalize=0[m]" \
-map "[m]" -c:a pcm_s16le -ar 48000 -ac 1 "$WORK/mix_cru.wav"

# loudnorm em dois passos: o passo único é dinâmico e não converge no alvo
echo "--> medindo para o loudnorm"
M=$(ffmpeg -hide_banner -nostats -i "$WORK/mix_cru.wav" \
     -af loudnorm=I=-14:TP=-1:LRA=11:print_format=json -f null - 2>&1 | sed -n '/{/,/}/p')
val() { echo "$M" | grep -oP "\"$1\"\s*:\s*\"\K[^\"]+"; }
TP_CRU=$(val input_tp)
GANHO=$(python3 -c "print(f'{-1 - ($TP_CRU):.2f}')")

echo "--> $PREFIXO"_sync.m4a" (-14 LUFS)"
ffmpeg_lim -hide_banner -nostats -v warning -y -i "$WORK/mix_cru.wav" -af \
"loudnorm=I=-14:TP=-1:LRA=11:measured_I=$(val input_i):measured_TP=$TP_CRU:\
measured_LRA=$(val input_lra):measured_thresh=$(val input_thresh):offset=$(val target_offset),aresample=48000" \
-c:a aac -b:a 256k -ar 48000 -ac 1 "${PREFIXO}_sync.m4a"

echo "--> ${PREFIXO}_sync_dinamico.m4a (ganho estático ${GANHO} dB)"
ffmpeg_lim -hide_banner -nostats -v warning -y -i "$WORK/mix_cru.wav" -af "volume=${GANHO}dB" \
-c:a aac -b:a 256k -ar 48000 -ac 1 "${PREFIXO}_sync_dinamico.m4a"

# Para a conferência os dois vão em canais separados, sem soma: assim dá para
# ouvir o encaixe. join, não amerge — o amerge embaralha os canais quando os
# dois lados são mono sem layout declarado.
DUR=$(python3 -c "
import subprocess
d=[float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','csv=p=0',p])) for p in ['$REF','$OUTRA']]
print(f'{max(d[0]+$DLY_REF/48000, d[1]+$DLY_OUTRA/48000):.3f}')")
echo "--> ${PREFIXO}_conferencia_LR.m4a (L=referência, R=outra, ${DUR}s)"
ffmpeg_lim -hide_banner -nostats -v warning -y -i "$REF" -i "$OUTRA" -filter_complex \
"[0:a]${FMT},adelay=${DLY_REF}S:all=1,volume=-5dB,apad=whole_dur=${DUR}[a];
 [1:a]${FMT},adelay=${DLY_OUTRA}S:all=1,volume=-1dB,apad=whole_dur=${DUR}[b];
 [a][b]join=inputs=2:channel_layout=stereo[m]" \
-map "[m]" -t "$DUR" -c:a aac -b:a 256k -ar 48000 "${PREFIXO}_conferencia_LR.m4a"

echo
for f in "${PREFIXO}_sync.m4a" "${PREFIXO}_sync_dinamico.m4a" "${PREFIXO}_conferencia_LR.m4a"; do
  echo "$(basename "$f"): $(ffmpeg -hide_banner -nostats -i "$f" -af ebur128=peak=true -f null - 2>&1 \
    | sed -n '/Summary/,$p' | grep -E '^    (I|LRA):|^    Peak:' | tr -s ' ' | tr '\n' ' ')"
done
