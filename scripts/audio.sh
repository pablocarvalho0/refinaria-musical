#!/usr/bin/env bash
# Tratamento de áudio por classe — passo 2 de docs/01-arquitetura-segmentacao.md.
#
# Produz o entregável de áudio a partir do _norm.mp4 do processa.sh, que
# carrega o vídeo já normalizado e o áudio ainda cru.
#
#   FALA    highpass 80 Hz + denoise leve + compressão suave + loudnorm I=-14
#   MUSICA  loudnorm I=-14 com LRA alto — sem denoise, sem compressão
#
# Uso: ./audio.sh out/ep00/ep00_norm.mp4              (por classe, precisa de segmentos.txt)
#      ./audio.sh out/ep00/ep00_norm.mp4 --uniforme   (classe única, não precisa)
#
# ---------------------------------------------------------------------
# Decisões que não são óbvias
# ---------------------------------------------------------------------
#
# 1. As duas cadeias rodam sobre o áudio INTEIRO, em paralelo, e são
#    misturadas por uma máscara com rampa — em vez de cortar em pedaços
#    e concatenar.
#    Concatenar pedaços processados esbarra em dois problemas: clique na
#    emenda, e latência de filtro que empurra a linha do tempo. A máscara
#    resolve os dois: a soma das duas máscaras é exatamente 1 em todo o
#    sinal (medido: erro de 0,0 LSB reconstruindo ruído branco), então
#    não há buraco nem estouro na transição, e nada muda de duração.
#
# 2. A latência do afftdn é compensada explicitamente.
#    Medido com impulso: afftdn atrasa 1200 amostras = 25,00 ms a 48 kHz.
#    highpass, acompressor e loudnorm têm latência zero. Sem compensar,
#    a cadeia de fala sairia 25 ms atrasada em relação à de música e a
#    mistura ficaria com comb filtering na rampa.
#
# 3. loudnorm em DOIS passos com linear=true.
#    Passo único é um normalizador dinâmico: ele persegue o alvo ao longo
#    do arquivo, e é exatamente isso que achata o violão — medido, 9,09 dB
#    de variação de ganho ao longo da música. Em dois passos com
#    linear=true ele vira ganho estático mais limitador de pico: acerta
#    -14 LUFS sem tocar na dinâmica (0,08 dB de variação). O LRA alto na
#    música existe para impedir que ele caia de volta no modo dinâmico.
#
#    Na fala o linear=true é inócuo e não há o que fazer: ela precisa de
#    +7 dB, o que levaria o pico a +2,69 dBTP, então o loudnorm volta ao
#    modo dinâmico. Para fala isso é o comportamento desejável.
#
# 4. Alinhamento por construção, verificado por medição.
#    Desde a v3 do processa.sh o áudio do _norm é bit-idêntico ao do
#    master, e tanto este script quanto a extração da transcrição usam
#    first_pts=0. Os timestamps do segmentos.txt e o áudio daqui vivem na
#    mesma linha do tempo sem correção nenhuma. O script confere isso
#    contra o .wav da transcrição e para se não bater — antes essa
#    defasagem existia e valia 21,33 ms.

set -euo pipefail
source "$(dirname "$(readlink -f "$0")")/lib.sh"

VIDEO="${1:?uso: $0 <video_norm.mp4> [--uniforme]}"
MODO="${2:-}"
[[ -f "$VIDEO" ]] || { echo "não encontrado: $VIDEO" >&2; exit 1; }

ROOT="$HOME/video"
BASE=$(basename "$VIDEO"); BASE="${BASE%.*}"; BASE="${BASE%_norm}"
WORK="$ROOT/work"
pasta_projeto "$VIDEO"
OUT="$PROJETO_DIR"
projeto_resumo

# O segmentos.txt agora é por episódio, dentro da pasta do projeto. O
# work/segmentos.txt continua sendo aceito como queda: é o nome antigo,
# global, e é justamente por ser global que ele saiu — dois masters
# processados em sequência sobrescreviam um ao outro sem avisar.
#
# Numa rodada de teste a busca começa na pasta da rodada — dá para
# sobrepor o segmentos localmente, se a rodada for justamente sobre isso —
# e cai na RAIZ do episódio, que é onde o segmenta.py escreve de verdade.
# Sem esse segundo degrau, todo audio.sh sob RODADA não acharia o arquivo
# e mandaria usar --uniforme: a cadeia errada, sem erro nenhum.
if [[ -z "${SEG:-}" ]]; then
  for _c in "$OUT/${BASE}.segmentos.txt" \
            "$PROJETO_RAIZ/${BASE}.segmentos.txt" \
            "$WORK/segmentos.txt"; do
    SEG="$_c"; [[ -f "$SEG" ]] && break
  done
fi
REF="${REF:-$WORK/${BASE}.wav}"      # wav da transcrição, para conferir alinhamento
PY="$ROOT/.venv/bin/python"
[[ -x "$PY" ]] || { echo "venv não encontrado em $PY" >&2; exit 1; }

UNIFORME=0
[[ "$MODO" == "--uniforme" ]] && UNIFORME=1
if [[ "$UNIFORME" -eq 0 && ! -f "$SEG" ]]; then
  echo "segmentos.txt não encontrado em $SEG" >&2
  echo "gere com:  python scripts/segmenta.py $WORK/${BASE}.wav" >&2
  echo "ou rode em classe única:  $0 $VIDEO --uniforme" >&2
  exit 1
fi

# Guarda: o segmentos.txt é deste vídeo?
#
# Mascarar com as regiões do episódio errado não dá erro nenhum — sai um
# arquivo íntegro, com a fala tratada como música e vice-versa, e só se
# percebe ouvindo. O risco não é teórico: até 05/09 o segmenta.py escrevia
# em work/segmentos.txt, nome global, e o audio.sh o pegava de olhos
# fechados. Num teste, um vídeo de 3s casou com o segmentos de 189s de
# outro episódio sem uma palavra de aviso.
#
# A conferência é a duração declarada no cabeçalho contra a do vídeo. É o
# dado que já está no arquivo — não custa medição nova, e um segmentos de
# outro episódio quase nunca tem a mesma duração.
if [[ "$UNIFORME" -eq 0 ]]; then
  DUR_SEG=$(sed -n 's/^# duracao total:.*(\([0-9.]*\)s)/\1/p' "$SEG" | head -1)
  DUR_VID=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$VIDEO")
  if [[ -n "$DUR_SEG" ]] \
     && ! awk -v a="$DUR_SEG" -v b="$DUR_VID" \
              'BEGIN{d=a-b; if(d<0)d=-d; exit !(d<=1.0)}'; then
    echo >&2
    echo "segmentos.txt não parece ser deste vídeo:" >&2
    echo "  $SEG declara ${DUR_SEG}s" >&2
    echo "  $(basename "$VIDEO") tem ${DUR_VID}s" >&2
    echo "Gere o certo:  python scripts/segmenta.py $WORK/${BASE}.wav" >&2
    echo "Ou aponte o seu:  SEG=<arquivo> $0 $VIDEO" >&2
    exit 1
  fi
  echo "    segmentos: ${SEG/#$HOME\//~/}  (${DUR_SEG}s ~ ${DUR_VID}s do vídeo)"
fi

LUFS="${LUFS:--14}"
TP="${TP:--1.5}"
LRA_FALA="${LRA_FALA:-11}"     # fala: faixa estreita, é o alvo do YouTube
LRA_MUSICA="${LRA_MUSICA:-20}" # música: faixa larga, para não virar modo dinâmico
LRA_UNIF="${LRA_UNIF:-11}"     # classe única: alvo padrão do YouTube
RAMPA="${RAMPA:-0.050}"        # s — largura da transição entre as duas cadeias
LAT_AFFTDN=0.025               # s — medido com impulso, ver cabeçalho

TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT

# =====================================================================
# 1. Áudio de trabalho, na linha do tempo do vídeo
#
# first_pts=0 preenche o começo com silêncio até o instante zero, que é
# o mesmo tratamento que o processa.sh dá ao .wav da transcrição. Sem
# isso o offset do stream de áudio (0,048896 s no ep00) seria descartado
# ao escrever o WAV e tudo sairia adiantado.
# =====================================================================
echo "==> 1/5  Extraindo audio na linha do tempo do video"
SRC="$WORK/${BASE}_work48.wav"
ffmpeg -v error -y -i "$VIDEO" -vn \
  -af "aresample=48000:async=1:first_pts=0" -ac 2 -c:a pcm_s16le "$SRC"

if [[ -f "$REF" ]]; then
  ffmpeg -v error -y -i "$SRC" -ac 1 -ar 16000 -c:a pcm_s16le "$TMP/a.wav"
  LAG=$("$PY" - "$TMP/a.wav" "$REF" <<'PY'
import sys, wave
import numpy as np

def ler(p):
    with wave.open(p) as w:
        return (np.frombuffer(w.readframes(w.getnframes()),
                              dtype=np.int16).astype(np.float64),
                w.getframerate())

a, sr = ler(sys.argv[1])
b, _ = ler(sys.argv[2])
n = min(len(a), len(b))
a, b = a[:n] - a[:n].mean(), b[:n] - b[:n].mean()
N = 1 << (2 * n - 1).bit_length()
c = np.fft.irfft(np.fft.rfft(a, N) * np.conj(np.fft.rfft(b, N)), N)
J = int(0.2 * sr)
c = np.concatenate([c[-J:], c[:J + 1]])
print(f"{(int(np.argmax(np.abs(c))) - J) / sr * 1000:.2f}")
PY
)
  echo "    alinhamento contra $(basename "$REF"): ${LAG} ms"
  # 1 ms é folga para o arredondamento do wav de 16 kHz da referência.
  "$PY" -c "
import sys
if abs(float('$LAG')) > 1.0:
    sys.exit('  ERRO: o audio esta $LAG ms fora da linha do tempo da '
             'transcricao. Os timestamps do segmentos.txt nao valem aqui. '
             'Reprocesse com o processa.sh v3.')"
else
  echo "    aviso: $REF não existe — alinhamento não verificado" >&2
fi

# =====================================================================
# 2. Cadeias por classe
# =====================================================================
# atrim+apad depois do afftdn devolve os 25 ms que ele empurra, sem mexer
# na duração total.
CAD_FALA="highpass=f=80,afftdn=nr=10:nf=-30,atrim=start=${LAT_AFFTDN},asetpts=PTS-STARTPTS,apad=pad_dur=${LAT_AFFTDN},acompressor=threshold=-18dB:ratio=3:attack=15:release=200"
CAD_MUSICA="anull"

# =====================================================================
# 3. Passo 1 do loudnorm: medir
#
# A medição roda sobre as regiões daquela classe concatenadas — medir o
# arquivo inteiro daria uma média que não serve para nenhuma das duas.
# O gating do EBU R128 já descarta as pausas, então concatenar não infla
# nem desinfla o resultado.
# =====================================================================
echo "==> 2/5  Medindo loudness (passo 1 do loudnorm)"

mede() {
  local rotulo="$1" filtro="$2"
  ffmpeg -hide_banner -nostats -i "$SRC" \
    -filter_complex "$filtro" -map "[m]" -f null - 2>&1 \
    | awk '/^\{/,/^\}/' > "$TMP/m_$rotulo.json"
  [[ -s "$TMP/m_$rotulo.json" ]] || { echo "medição de $rotulo falhou" >&2; exit 1; }
  "$PY" -c "
import json
d = json.load(open('$TMP/m_$rotulo.json'))
v = tuple(float(d[k]) for k in ('input_i', 'input_tp', 'input_lra', 'input_thresh'))
print('    %-7s I=%7.2f  TP=%6.2f  LRA=%5.2f  thresh=%7.2f  (passo 1: %s)'
      % (('$rotulo',) + v + (d['normalization_type'],)))"
}

mede_classe() {
  local classe="$1" cadeia="$2" lra="$3"
  "$PY" - "$SEG" "$classe" "$cadeia" "$lra" "$LUFS" "$TP" > "$TMP/f_$classe.txt" <<'PY'
import sys
seg, classe, cadeia, lra, lufs, tp = sys.argv[1:7]
regs = []
for linha in open(seg, encoding="utf-8"):
    if linha.startswith("#") or not linha.strip():
        continue
    campos = linha.split()
    if len(campos) < 3 or campos[0] != classe:
        continue
    def s(x):
        h, m, sec = x.split(":")
        return int(h) * 3600 + int(m) * 60 + float(sec)
    regs.append((s(campos[1]), s(campos[2])))
if not regs:
    sys.exit(f"nenhuma regiao {classe} em {seg}")
p = []
for i, (a, b) in enumerate(regs):
    p.append(f"[0:a]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS[t{i}];")
p.append("".join(f"[t{i}]" for i in range(len(regs))))
p.append(f"concat=n={len(regs)}:v=0:a=1,{cadeia},"
         f"loudnorm=I={lufs}:TP={tp}:LRA={lra}:print_format=json[m]")
print("".join(p))
PY
  mede "$classe" "$(cat "$TMP/f_$classe.txt")"
}

if [[ "$UNIFORME" -eq 1 ]]; then
  # Modo de classe única: sem denoise, sem compressão, sem separar nada.
  # Existe para o episódio cuja zona cinzenta estoura o critério de 10%,
  # ou para quando não vale a pena segmentar. Mesmo assim é melhor que o
  # loudnorm de passo único da v2 do processa.sh, porque em dois passos
  # com linear=true não fica andando em cima do violão.
  mede UNICO "[0:a]${CAD_MUSICA},loudnorm=I=${LUFS}:TP=${TP}:LRA=${LRA_UNIF}:print_format=json[m]"
else
  mede_classe FALA   "$CAD_FALA"   "$LRA_FALA"
  mede_classe MUSICA "$CAD_MUSICA" "$LRA_MUSICA"
fi

# =====================================================================
# 4. Passo 2: renderizar
# =====================================================================
echo "==> 3/5  Montando o grafo de filtros"
if [[ "$UNIFORME" -eq 1 ]]; then
  "$PY" - "$CAD_MUSICA" "$TMP/m_UNICO.json" "$LUFS" "$TP" "$LRA_UNIF" \
      > "$TMP/render.txt" <<'PY'
import json, sys
cadeia, j, lufs, tp, lra = sys.argv[1:6]
d = json.load(open(j))
print(f"[0:a]{cadeia},loudnorm=I={lufs}:TP={tp}:LRA={lra}:linear=true"
      f":measured_I={d['input_i']}:measured_TP={d['input_tp']}"
      f":measured_LRA={d['input_lra']}:measured_thresh={d['input_thresh']}"
      f":offset={d['target_offset']},apad[a]")
PY
else
  "$PY" - "$SEG" "$RAMPA" "$CAD_FALA" "$CAD_MUSICA" \
         "$TMP/m_FALA.json" "$TMP/m_MUSICA.json" \
         "$LUFS" "$TP" "$LRA_FALA" "$LRA_MUSICA" > "$TMP/render.txt" <<'PY'
import json, sys
(seg, rampa, cad_f, cad_m, jf, jm, lufs, tp, lra_f, lra_m) = sys.argv[1:11]
R = float(rampa)

def segundos(x):
    h, m, s = x.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)

fala = []
for linha in open(seg, encoding="utf-8"):
    if linha.startswith("#") or not linha.strip():
        continue
    c = linha.split()
    if len(c) >= 3 and c[0] == "FALA":
        fala.append((segundos(c[1]), segundos(c[2])))
if not fala:
    sys.exit("nenhuma regiao FALA — use --uniforme")

# Máscara trapezoidal: sobe em R segundos na entrada da fala, desce em R
# na saída. Somada sobre as regiões e limitada a 1. A cadeia de música
# recebe o complemento, então as duas somam exatamente 1 em todo ponto —
# a rampa é um crossfade linear entre dois sinais correlacionados, que
# não produz nem buraco nem pico.
termos = [f"max(0\\,min(1\\,min((t-{a:.3f})/{R}\\,({b:.3f}-t)/{R})))"
          for a, b in fala]
mascara = f"min(1\\,{'+'.join(termos)})" if len(termos) > 1 else termos[0]

def ln(j, lra):
    d = json.load(open(j))
    return (f"loudnorm=I={lufs}:TP={tp}:LRA={lra}:linear=true"
            f":measured_I={d['input_i']}:measured_TP={d['input_tp']}"
            f":measured_LRA={d['input_lra']}:measured_thresh={d['input_thresh']}"
            f":offset={d['target_offset']}")

# asetnsamples antes do volume: o volume com eval=frame reavalia a
# expressão uma vez por frame, e frames grandes tornariam a rampa
# degrauzada. 256 amostras = 5,3 ms de resolução, folgado para R=50 ms.
#
# O ffmpeg avisa "Invalid value NaN for volume, setting to 0" uma vez por
# ramo. É o frame de flush do EOF, que não tem pts — 't' vira NaN. Não
# afeta o conteúdo: renderizando DC pelas duas máscaras, a soma dá
# 1.000000 em todas as amostras do sinal. Acontece com p=0 e com p=1.
#
# apad no fim: o áudio termina alguns ms antes do vídeo, e sem isso o
# -shortest apara o VÍDEO em vez do áudio — mediu-se um frame a menos.
print(
    "[0:a]asplit=2[s][m];"
    f"[s]{cad_f},{ln(jf, lra_f)},asetnsamples=n=256:p=0,"
    f"volume=volume='{mascara}':eval=frame[sg];"
    f"[m]{cad_m},{ln(jm, lra_m)},asetnsamples=n=256:p=0,"
    f"volume=volume='1-({mascara})':eval=frame[mg];"
    "[sg][mg]amix=inputs=2:duration=longest:normalize=0,apad[a]"
)
PY
fi

echo "==> 4/5  Renderizando audio e remuxando"
# O vídeo é copiado sem reencode: nenhuma geração nova de perda, e o
# arquivo já está em 1920x1080 / 60 CFR / yuv420p.
#
# O áudio entra PRIMEIRO de propósito: o grafo referencia [0:a], e o
# mesmo grafo é usado na medição, onde $SRC é a única entrada. Inverter
# a ordem faria o render processar o áudio do container de vídeo. Já
# aconteceu; por isso o comentário.
time ffmpeg_lim -y -hide_banner -loglevel warning -stats \
  -i "$SRC" -i "$VIDEO" \
  -filter_complex_script "$TMP/render.txt" \
  -map 1:v:0 -map "[a]" \
  -c:v copy \
  -c:a aac -b:a 192k -ar 48000 \
  -metadata:s:a:0 language=por \
  -shortest -movflags +faststart \
  "$OUT/${BASE}_audio.mp4"

echo
echo "==> 5/5  Conferindo"
ffprobe -v error -show_entries stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels -of default=noprint_wrappers=1 "$OUT/${BASE}_audio.mp4"
ffprobe -v error -show_entries format=duration,size -of default=noprint_wrappers=1 "$OUT/${BASE}_audio.mp4"
echo
ls -lh "$VIDEO" "$OUT/${BASE}_audio.mp4"
echo
echo "Medir o resultado:"
echo "  ./scripts/mede-audio.sh $OUT/${BASE}_audio.mp4 $SEG"
