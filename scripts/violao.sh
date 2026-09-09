#!/usr/bin/env bash
# Tratamento de audio para violao solo instrumental — sem fala no trecho.
#
# Existe porque o audio.sh nao serve para este caso: a cadeia dele de
# MUSICA e um loudnorm e nada mais, e a de FALA tem denoise e compressor,
# que sao justamente os dois filtros que estragam um dedilhado. Este
# script troca o compressor por um ganho lento e joga o denoise fora.
#
# Uso:
#   ./scripts/violao.sh <entrada.mp4|wav> [opcoes]
#
#   --inicio S       comeco do trecho, em segundos (padrao 0)
#   --duracao S      duracao do trecho; a saida tem EXATAMENTE isto
#   --saida ARQ      wav de saida (padrao work/<base>_violao.wav)
#   --reverb NOME    conv (padrao) | freeverb | nenhum
#   --wet dB         nivel do reverb (padrao -15.5)
#   --rt60 S         cauda do reverb conv (padrao 1.3)
#   --predelay MS    (padrao 25)
#   --hpf HZ         (padrao 70; 0 desliga)
#   --rider DB       teto do ganho lento (padrao 3; 0 desliga)
#   --brilho DB      high shelf em 8 kHz (padrao 0 — fora da cadeia)
#   --lufs / --tp    alvos (padrao -14 LUFS, -1 dBTP)
#   --ab             tambem gera as variantes curtas de comparacao
#   --ab-janela A:B  trecho das variantes (padrao 15 s a partir da metade)
#
# ---------------------------------------------------------------------
# A fonte e o _norm.mp4, nunca o _audio.mp4
# ---------------------------------------------------------------------
# Desde a v3 do processa.sh o audio do _norm e bit-identico ao do celular.
# O _audio.mp4 ja passou pelo loudnorm e pelo afftdn do audio.sh; tratar
# em cima dele mediria este trabalho sobre audio ja estragado. E o mesmo
# principio que o audio.sh aplica quando busca o master em vez do _norm.
#
# A extracao usa first_pts=0 pelo motivo de sempre: o stream de audio nao
# comeca em zero e o WAV descarta esse offset ao ser escrito.
#
# ---------------------------------------------------------------------
# Por que convolucao e nao aecho — medido em 05/09/2026
# ---------------------------------------------------------------------
# Tres abordagens foram medidas no mesmo trecho, com a quantidade de
# reverb casada pela mesma queda de "profundidade do dedilhado":
#
#   aecho do ffmpeg      correlacao L/R 1,0000 — nao abre nada. A fonte e
#                        mono somado (correlacao 1,0000, diferenca 72 dB
#                        abaixo), entao o aecho devolve mono. Alem disso
#                        ondula o espectro em 2,12 dB com um vale de
#                        -5,14 dB, e a cauda dura 0,14 s: sao ecos soltos,
#                        nao uma sala. Descartado.
#
#   Freeverb/pedalboard  abre (correlacao 0,979, lado 19,8 dB abaixo do
#                        centro), mas ondula 1,27 dB e a cauda e menos
#                        densa: crest de 12,1 dB entre 100 e 400 ms.
#
#   convolucao (esta)    ondula 1,10 dB, cauda com crest de 10,4 dB — a
#                        mais densa das tres — e abre igual (0,976 / 19,2).
#
# Nenhuma das tres mexeu no ataque: a diferenca pareada de tempo de
# subida ficou entre +0,00 e +0,04 ms, com incerteza de +-1 ms, nas nove
# configuracoes medidas. Foi preciso PAREAR nota a nota para ver isso —
# a mediana solta do tempo de subida tem erro-padrao de 1,94 ms e chegou
# a acusar +2,8 ms de diferenca que nao existe.
# ---------------------------------------------------------------------

set -euo pipefail
source "$(dirname "$(readlink -f "$0")")/lib.sh"

RAIZ="$(dirname "$(dirname "$(readlink -f "$0")")")"
PY="$RAIZ/.venv/bin/python"
DSP="$(dirname "$(readlink -f "$0")")/violao_dsp.py"
[[ -x "$PY" ]] || { echo "venv nao encontrado em $PY" >&2; exit 1; }

ENTRADA="${1:?uso: $0 <entrada> [opcoes]}"; shift
[[ -f "$ENTRADA" ]] || { echo "nao encontrado: $ENTRADA" >&2; exit 1; }

INICIO=0; DURACAO=""; SAIDA=""; AB=0; AB_JANELA=""
DSP_ARGS=()
while (( $# )); do
  case "$1" in
    --inicio)     INICIO="$2"; shift 2 ;;
    --duracao)    DURACAO="$2"; shift 2 ;;
    --saida)      SAIDA="$2"; shift 2 ;;
    --ab)         AB=1; shift ;;
    --ab-janela)  AB_JANELA="$2"; shift 2 ;;
    --reverb|--wet|--rt60|--predelay|--hpf|--rider|--rider-suave|--brilho|--lufs|--tp)
                  DSP_ARGS+=("$1" "$2"); shift 2 ;;
    *) echo "opcao desconhecida: $1" >&2; exit 1 ;;
  esac
done

BASE=$(basename "$ENTRADA"); BASE="${BASE%.*}"; BASE="${BASE%_norm}"
TRABALHO="$RAIZ/work"
mkdir -p "$TRABALHO"
[[ -n "$SAIDA" ]] || SAIDA="$TRABALHO/${BASE}_violao.wav"

case "$ENTRADA" in
  *_audio.mp4|*_cover.mp4|*_final.mp4)
    echo "aviso: '$ENTRADA' ja passou pela cadeia do audio.sh." >&2
    echo "       Trate a partir do _norm.mp4 — ver o cabecalho deste script." >&2 ;;
esac

TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
CRU="$TMP/cru.wav"

# =====================================================================
# 1. Extrair o trecho, na linha do tempo do arquivo de origem
#
# O -ss e o -t entram DEPOIS do -af de proposito: como opcao de saida
# eles agem sobre o que ja saiu do filtro, entao o first_pts=0 completa
# o comeco ate o instante zero do arquivo e so depois o trecho e
# recortado. Na ordem inversa o offset do stream entraria no recorte.
# =====================================================================
echo "==> 1/3  Extraindo o trecho de $ENTRADA"
CORTE=(-ss "$INICIO")
[[ -n "$DURACAO" ]] && CORTE+=(-t "$DURACAO")
ffmpeg_lim -v error -y -i "$ENTRADA" -vn \
  -af "aresample=48000:async=1:first_pts=0" \
  "${CORTE[@]}" -c:a pcm_s24le -ar 48000 "$CRU"

CANAIS=$(ffprobe -v error -select_streams a:0 -show_entries stream=channels \
         -of default=nw=1:nk=1 "$CRU")
AMOSTRAS=0
if [[ -n "$DURACAO" ]]; then
  AMOSTRAS=$("$PY" -c "print(int(round(float('$DURACAO')*48000)))")
  TEM=$("$PY" -c "
import soundfile as sf; print(sf.info('$CRU').frames)")
  if (( TEM != AMOSTRAS )); then
    echo "    aviso: a fonte tem $TEM amostras no trecho, faltam $((AMOSTRAS-TEM))"
    echo "           para os $AMOSTRAS pedidos — a saida sera completada ate a duracao exata."
  fi
fi
echo "    $CANAIS canal(is), 48 kHz"

# =====================================================================
# 2. Tratar
# =====================================================================
echo "==> 2/3  Tratando"
"$PY" "$DSP" "$CRU" "$SAIDA" --amostras "$AMOSTRAS" "${DSP_ARGS[@]}"

# =====================================================================
# 3. Variantes de A/B — a escolha do reverb e do ouvido, nao da medida
#
# As medidas separam o que e defeito (aecho nao abre, denoise come a
# unha) do que e gosto (quanta sala). Quanta sala ninguem mede: por isso
# saem quatro arquivos curtos e alinhados, para o autor comparar.
# =====================================================================
if (( AB )); then
  echo "==> 3/3  Variantes de comparacao"
  if [[ -z "$AB_JANELA" ]]; then
    DUR=$("$PY" -c "
import soundfile as sf; print(sf.info('$CRU').frames/48000)")
    AB_JANELA=$("$PY" -c "
d=float('$DUR'); i=max(0.0, d/2-7.5); print('%.3f:%.3f' % (i, min(d, i+15)))")
  fi
  echo "    janela: $AB_JANELA s do trecho"
  DIR=$(dirname "$SAIDA")
  ab() {  # nome  args...
    local nome="$1"; shift
    "$PY" "$DSP" "$CRU" "$DIR/ab_${nome}.wav" --recorte "$AB_JANELA" "$@"
  }
  ab 0_seca                --reverb nenhum
  ab 1_conv_medio          --reverb conv --wet -15.5 --rt60 1.3 --predelay 25
  ab 2_conv_amplo          --reverb conv --wet -12.0 --rt60 1.8 --predelay 25
  ab 3_freeverb_medio      --reverb freeverb --wet -15.5
else
  echo "==> 3/3  (sem --ab, nenhuma variante gerada)"
fi

echo
echo "Pronto: $SAIDA"
