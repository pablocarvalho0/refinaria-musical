#!/usr/bin/env bash
# Tratamento de áudio por classe — passo 2 de docs/01-arquitetura-segmentacao.md.
#
# Aplica cadeias distintas às regiões FALA e MUSICA e remonta. Só rodar
# depois que scripts/segmenta.py tiver medido a zona cinzenta abaixo do
# critério de 10% para o episódio.
#
#   FALA    highpass 80 Hz + denoise leve + compressão suave + loudnorm I=-14
#   MUSICA  loudnorm I=-14 com LRA alto — sem denoise, sem compressão
#
# Uso: ./audio.sh work/ep00.mp4
#      (deriva out/ep00_norm.mp4 e work/segmentos.txt do nome base)
#
# ---------------------------------------------------------------------
# Três decisões que este script toma e que não são óbvias
# ---------------------------------------------------------------------
#
# 1. A fonte é o MASTER, não o _norm.mp4.
#    O _norm já levou um loudnorm de passo único, que é dinâmico e já
#    achatou o violão. Reprocessar em cima disso mediria o tratamento
#    diferenciado sobre um áudio estragado. O vídeo vem do _norm (cópia
#    de stream, sem reencode); o áudio vem do master.
#
# 2. As duas cadeias rodam sobre o áudio INTEIRO, em paralelo, e são
#    misturadas por uma máscara com rampa — em vez de cortar em pedaços
#    e concatenar.
#    Concatenar pedaços processados esbarra em dois problemas: clique na
#    emenda, e latência de filtro que empurra a linha do tempo. A máscara
#    resolve os dois: a soma das duas máscaras é exatamente 1 em todo o
#    sinal (medido: erro de 0,0 LSB reconstruindo ruído branco), então
#    não há buraco nem estouro na transição, e nada muda de duração.
#
# 3. A latência do afftdn é compensada explicitamente.
#    Medido com impulso: afftdn atrasa 1200 amostras = 25,00 ms a 48 kHz.
#    highpass, acompressor e loudnorm têm latência zero. Sem compensar,
#    a cadeia de fala sairia 25 ms atrasada em relação à de música e a
#    mistura ficaria com comb filtering na rampa.
#
# ---------------------------------------------------------------------
# Por que loudnorm em dois passos com linear=true
# ---------------------------------------------------------------------
# loudnorm de passo único é um normalizador DINÂMICO: ele persegue o alvo
# ao longo do arquivo, o que é exatamente o que achata o violão. Em dois
# passos com linear=true ele vira ganho estático mais limitador de pico —
# acerta -14 LUFS sem tocar na dinâmica. O LRA alto na música existe para
# impedir que ele caia de volta no modo dinâmico.

set -euo pipefail

MASTER="${1:?uso: $0 <master.mp4>}"
[[ -f "$MASTER" ]] || { echo "não encontrado: $MASTER" >&2; exit 1; }

ROOT="$HOME/video"
BASE=$(basename "$MASTER"); BASE="${BASE%.*}"
WORK="$ROOT/work"; OUT="$ROOT/out"
VIDEO="${VIDEO:-$OUT/${BASE}_norm.mp4}"
SEG="${SEG:-$WORK/segmentos.txt}"
PY="$ROOT/.venv/bin/python"

for f in "$VIDEO" "$SEG" "$PY"; do
  [[ -e "$f" ]] || { echo "não encontrado: $f" >&2; exit 1; }
done

LUFS="${LUFS:--14}"
TP="${TP:--1.5}"
LRA_FALA="${LRA_FALA:-11}"     # fala: faixa estreita, é o alvo do YouTube
LRA_MUSICA="${LRA_MUSICA:-20}" # música: faixa larga, para não virar modo dinâmico
RAMPA="${RAMPA:-0.050}"        # s — largura da transição entre as duas cadeias
LAT_AFFTDN=0.025               # s — medido com impulso, ver cabeçalho

TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT

# =====================================================================
# 1. Alinhamento
#
# O .wav que gerou a transcrição saiu do _norm.mp4; os timestamps do
# segmentos.txt vivem naquela linha do tempo. O master tem outra: os
# streams de áudio começam em start_time diferentes (o WAV descarta esse
# offset ao ser escrito, porque WAV não tem timestamp). Medir a defasagem
# por correlação cruzada e corrigir, em vez de supor que é zero.
# =====================================================================
echo "==> 1/5  Alinhando o áudio do master à linha do tempo do _norm"
ffmpeg -v error -y -i "$MASTER" -vn -ac 1 -ar 48000 -t 90 -c:a pcm_s16le "$TMP/a.wav"
ffmpeg -v error -y -i "$VIDEO"  -vn -ac 1 -ar 48000 -t 90 -c:a pcm_s16le "$TMP/b.wav"

LAG=$("$PY" - "$TMP/a.wav" "$TMP/b.wav" <<'PY'
import sys, wave
import numpy as np

def ler(p):
    with wave.open(p) as w:
        a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return a.astype(np.float64), w.getframerate()

a, sr = ler(sys.argv[1])
b, _ = ler(sys.argv[2])
n = min(len(a), len(b))
a, b = a[:n] - a[:n].mean(), b[:n] - b[:n].mean()
N = 1 << (2 * n - 1).bit_length()
c = np.fft.irfft(np.fft.rfft(a, N) * np.conj(np.fft.rfft(b, N)), N)
# Só faz sentido procurar defasagem pequena: ±200 ms. Fora disso seria
# outro conteúdo, não desalinhamento.
J = int(0.2 * sr)
c = np.concatenate([c[-J:], c[:J + 1]])
lag = int(np.argmax(np.abs(c))) - J
# lag<0: o master adianta o norm -> atrasar o master em -lag amostras.
print(f"{-lag / sr:.6f}")
PY
)
echo "    defasagem master -> norm: ${LAG}s"

# Aplica a correção e materializa o áudio do master já alinhado, a 48 kHz
# estéreo. Os passos seguintes leem daqui, então a correção acontece uma
# vez só e não pode divergir entre a medição e a renderização.
ALINHA=$("$PY" -c "
l = float('$LAG')
print(f'adelay={int(round(l*1000))}:all=1' if l >= 0 else
      f'atrim=start={-l:.6f},asetpts=PTS-STARTPTS')")
echo "    filtro de alinhamento: $ALINHA"

SRC="$WORK/${BASE}_master48.wav"
ffmpeg -v error -y -i "$MASTER" -vn -af "$ALINHA" \
  -ac 2 -ar 48000 -c:a pcm_s16le "$SRC"

# =====================================================================
# 2. Cadeias por classe
# =====================================================================
# atrim+apad depois do afftdn devolve os 25 ms que ele empurra, sem mexer
# na duração total.
CAD_FALA="highpass=f=80,afftdn=nr=10:nf=-30,atrim=start=${LAT_AFFTDN},asetpts=PTS-STARTPTS,apad=pad_dur=${LAT_AFFTDN},acompressor=threshold=-18dB:ratio=3:attack=15:release=200"
CAD_MUSICA="anull"

# =====================================================================
# 3. Passo 1 do loudnorm: medir cada classe separadamente
#
# A medição roda sobre as regiões daquela classe concatenadas — medir o
# arquivo inteiro daria uma média que não serve para nenhuma das duas.
# O gating do EBU R128 já descarta as pausas, então concatenar não infla
# nem desinfla o resultado.
# =====================================================================
echo "==> 2/5  Medindo loudness de cada classe (passo 1 do loudnorm)"

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
  ffmpeg -hide_banner -nostats -i "$SRC" \
    -filter_complex_script "$TMP/f_$classe.txt" -map "[m]" -f null - 2>&1 \
    | awk '/^\{/,/^\}/' > "$TMP/m_$classe.json"
  [[ -s "$TMP/m_$classe.json" ]] || { echo "medição de $classe falhou" >&2; exit 1; }
  "$PY" -c "
import json
d = json.load(open('$TMP/m_$classe.json'))
print('    $classe  I=%7.2f  TP=%6.2f  LRA=%5.2f  thresh=%7.2f'
      % tuple(float(d[k]) for k in
              ('input_i', 'input_tp', 'input_lra', 'input_thresh')))"
}

mede_classe FALA   "$CAD_FALA"   "$LRA_FALA"
mede_classe MUSICA "$CAD_MUSICA" "$LRA_MUSICA"

# =====================================================================
# 4. Passo 2: renderizar com as duas cadeias em paralelo e misturar
# =====================================================================
echo "==> 3/5  Montando o grafo de filtros"
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
    sys.exit("nenhuma regiao FALA")

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
print(
    "[0:a]asplit=2[s][m];"
    f"[s]{cad_f},{ln(jf, lra_f)},asetnsamples=n=256:p=0,"
    f"volume=volume='{mascara}':eval=frame[sg];"
    f"[m]{cad_m},{ln(jm, lra_m)},asetnsamples=n=256:p=0,"
    f"volume=volume='1-({mascara})':eval=frame[mg];"
    # apad no fim: o áudio alinhado termina alguns ms antes do vídeo, e
    # sem isso o -shortest apara o VÍDEO em vez do áudio — mediu-se um
    # frame a menos que o _norm. Com o apad o áudio é sempre o mais
    # longo, e o -shortest corta o silêncio de sobra, preservando os
    # 11377 frames.
    "[sg][mg]amix=inputs=2:duration=longest:normalize=0,apad[a]"
)
PY

echo "==> 4/5  Renderizando áudio e remuxando com o vídeo do _norm"
# O vídeo é copiado sem reencode: nenhuma geração nova de perda, e o
# arquivo já está em 1920x1080 / 60 CFR / yuv420p, que é o pré-requisito
# do concat mais adiante.
# O áudio entra PRIMEIRO de propósito: o grafo gerado referencia [0:a], e
# o mesmo grafo é usado no passo de medição, onde $SRC é a única entrada.
# Inverter a ordem aqui faria o render processar o áudio do _norm — que já
# levou loudnorm — em vez do master, e a correção de ganho sairia aplicada
# sobre o arquivo errado. Já aconteceu; por isso o comentário.
time ffmpeg -y -hide_banner -loglevel warning -stats \
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
echo "Comparar com o loudnorm uniforme:"
echo "  ./scripts/mede-audio.sh $VIDEO $SEG"
echo "  ./scripts/mede-audio.sh $OUT/${BASE}_audio.mp4 $SEG"
