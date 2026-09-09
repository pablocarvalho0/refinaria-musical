#!/usr/bin/env python3
"""
Mede a FORMA de um trecho instrumental: onde comecam e terminam as secoes.

Vizinho do segmenta.py. Aquele parte o episodio em FALA/MUSICA a partir da
transcricao; este olha so para dentro da musica e procura as fronteiras de
secao, para que uma legenda de harmonia (acorde + funcao) possa ser
sincronizada em cima.

NAO faz reconhecimento de acordes — decisao ja registrada no CLAUDE.md
("Reconhecimento automatico de acordes descartado": 25 classes a ~67%, sem
setimas nem extensoes). O que ele estima e o CENTRO TONAL de cada bloco, que
e uma media sobre dezenas de compassos, robusta por construcao, e nao uma
decisao acorde a acorde. O autor sabe os acordes; o que falta e o *quando*.

O que ele mede:

  1. Grade. BPM, compasso e a fase do tempo forte. Fronteira de secao que nao
     cai em fronteira de compasso e suspeita, entao cada fronteira sai com o
     desvio em milissegundos para a grade.

  2. Fronteiras, por VARREDURA DE ESCALA. Novidade de Foote sobre matriz de
     auto-similaridade, em duas familias de descritor independentes — croma
     (harmonia) e MFCC (timbre) — e em varios tamanhos de kernel. O que
     interessa nao e o pico de uma configuracao: e quantas configuracoes
     acham a mesma fronteira. Uma terceira leitura, em janela fixa de 1s,
     entra como controle independente do rastreador de tempos.

  3. Centro tonal por bloco (Krumhansl-Kessler), sempre com a distancia para
     o segundo candidato de outra tonica.

  4. Repeticao: quais blocos sao repeticao de quais, tambem com a distancia
     para o segundo melhor par.

Toda pontuacao sai acompanhada da separacao para o segundo candidato. O
CLAUDE.md registra o caso do oficina-g3, em que a correlacao mentiu com
confianca alta em todas as 23 janelas porque musica casa consigo mesma a cada
compasso. Pico alto nao e prova; separacao e. Sem separacao, o script escreve
INCONCLUSIVO — que neste projeto e resultado, nao falha.

Entrada:  qualquer arquivo que o ffmpeg leia (mp4, wav, ...)
Saida:    <destino>.secoes.tsv  e  <destino>.secoes.png

Uso:
  python scripts/secoes.py out/improviso_3/improviso_3_norm.mp4 \\
      --inicio 41.0 --dur 60.7 --destino work/improviso_3_cover

Os tempos do TSV e da figura sao RELATIVOS ao inicio do trecho: 0.000 e o
--inicio dentro do arquivo de origem.
"""
import argparse
import pathlib
import shutil
import subprocess
import sys
import tempfile

import numpy as np

# ---------------------------------------------------------------------------
# Parametros da medicao, todos no topo para serem ajustados depois de olhar a
# figura — mesma convencao do legenda.py.
# ---------------------------------------------------------------------------
SR = 22050            # Hz — basta para croma; o CQT vai ate ~C7
HOP = 512             # amostras (23,2 ms a 22050 Hz)
BINS_OITAVA = 36      # 3 bins por semitom no CQT, antes de dobrar em croma
KERNELS = "12,16,20,24,32"   # tamanhos do checkerboard, em tempos
JANELA_FIXA = 1.0     # s — grade da leitura de controle
KERNEL_FIXO = 12.0    # s — checkerboard da leitura de controle
MIN_COMPASSOS = 4     # duas fronteiras mais perto que isso viram uma
TOL_COMPASSOS = 1.0   # duas fronteiras dentro disso sao a mesma fronteira
DELTA_PICO = 0.15     # fracao do maximo da novidade: piso para um pico contar
ESTABILIDADE = 0.60   # fracao dos kernels que precisa achar a fronteira
COMPASSO = 4          # tempos por compasso assumidos
LIM_GRUPO = 0.60      # cosseno acima disso agrupa dois blocos no mesmo rotulo
SEP_TONAL_OK = 0.15   # separacao KK acima disso e "confiavel"
SEP_TONAL_FRACA = 0.07
SEP_REPET_OK = 0.10   # separacao de cosseno acima disso e par "claro"

# Krumhansl-Kessler. Servem aqui porque medem PERMANENCIA — quanto cada grau
# soa ao longo do bloco inteiro —, nao qual acorde esta soando agora.
KK_MAIOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09,
                     2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
KK_MENOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53,
                     2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
NOTAS = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def hms(s: float) -> str:
    m, seg = divmod(max(s, 0.0), 60)
    return f"{int(m):02d}:{seg:06.3f}"


# ---------------------------------------------------------------------------
# Extracao
# ---------------------------------------------------------------------------
def extrai_wav(origem, inicio, dur, destino, sr):
    """Fatia o audio com ffmpeg.

    `first_pts=0` esta aqui pelo mesmo motivo do processa.sh: o stream de
    audio nao comeca em zero e o WAV descarta esse offset ao ser escrito.
    Sem isso todo timestamp herdaria o vies (27 ms medidos no ep00).
    """
    cmd = ["ffmpeg", "-v", "error", "-y", "-ss", f"{inicio:.6f}"]
    if dur is not None:
        cmd += ["-t", f"{dur:.6f}"]
    cmd += ["-i", str(origem), "-vn",
            "-af", "aresample=async=1:first_pts=0",
            "-ac", "1", "-ar", str(sr), "-c:a", "pcm_s16le", str(destino)]
    subprocess.run(cmd, check=True)


# ---------------------------------------------------------------------------
# Auto-similaridade e novidade de Foote
# ---------------------------------------------------------------------------
def similaridade(feat):
    """Matriz de auto-similaridade por cosseno. feat: (n_dims, n_quadros)."""
    x = feat - feat.mean(axis=0, keepdims=True)
    x = x / np.maximum(np.linalg.norm(x, axis=0, keepdims=True), 1e-9)
    return np.clip(x.T @ x, -1.0, 1.0)


def kernel_checkerboard(m):
    """Checkerboard gaussiano de lado 2m+1 (Foote, 2000)."""
    eixo = np.arange(-m, m + 1)
    gx, gy = np.meshgrid(eixo, eixo)
    gauss = np.exp(-0.5 * ((gx / (m / 2.0)) ** 2 + (gy / (m / 2.0)) ** 2))
    k = gauss * np.sign(gx) * np.sign(gy)
    return k / np.abs(k).sum()


def novidade(ssm, m):
    """Curva de novidade: o kernel desliza pela diagonal da SSM."""
    n = ssm.shape[0]
    k = kernel_checkerboard(m)
    pad = np.pad(ssm, m, mode="edge")
    curva = np.array([float((pad[i:i + 2 * m + 1, i:i + 2 * m + 1] * k).sum())
                      for i in range(n)])
    curva = np.maximum(curva, 0.0)
    return curva / curva.max() if curva.max() > 0 else curva


def picos(curva, tempos, min_sep, delta):
    """Maximos locais acima do piso, com separacao minima em segundos.

    Guloso pela altura, como o capa.py faz com os frames candidatos: sem
    reservar a vizinhanca, os melhores candidatos sao o mesmo instante
    repetido.
    """
    piso = delta * curva.max() if curva.max() > 0 else 0.0
    cand = [(float(curva[i]), float(tempos[i]))
            for i in range(1, len(curva) - 1)
            if curva[i] >= curva[i - 1] and curva[i] > curva[i + 1]
            and curva[i] >= piso]
    cand.sort(reverse=True)
    aceitos = []
    for alt, t in cand:
        if all(abs(t - ta) >= min_sep for ta, _ in aceitos):
            aceitos.append((t, alt))
    aceitos.sort()
    return aceitos


def agrupa(itens, tol):
    """Agrupa (tempo, ...) que caiam dentro de `tol` uns dos outros."""
    grupos = []
    for it in sorted(itens):
        if grupos and it[0] - grupos[-1][-1][0] <= tol:
            grupos[-1].append(it)
        else:
            grupos.append([it])
    return grupos


# ---------------------------------------------------------------------------
# Tonalidade
# ---------------------------------------------------------------------------
def centro_tonal(croma_medio):
    """Correlaciona o perfil de croma com as 24 tonalidades.

    O segundo candidato so conta se tiver OUTRA tonica: relativa e paralela
    compartilham quase todo o material e sempre aparecem coladas, entao
    empatar com elas nao e sinal de medicao ruim.
    """
    v = croma_medio - croma_medio.mean()
    dv = np.linalg.norm(v)
    res = []
    for i in range(12):
        for nome, perfil in (("maior", KK_MAIOR), ("menor", KK_MENOR)):
            p = np.roll(perfil, i)
            p = p - p.mean()
            res.append((float(v @ p / max(dv * np.linalg.norm(p), 1e-9)),
                        f"{NOTAS[i]} {nome}"))
    res.sort(reverse=True)
    r1, rot1 = res[0]
    tonica1 = rot1.split()[0]
    r2, rot2 = next(((r, x) for r, x in res[1:] if x.split()[0] != tonica1),
                    (0.0, "-"))
    return rot1, r1, rot2, r2, r1 - r2


def classes_distintivas(perfil, global_, n=3):
    """Classes de altura que mais distinguem o bloco da peca inteira.

    Modulacao aparece aqui antes de aparecer no rotulo de tonalidade: um
    bloco que empresta acorde de fora do campo levanta a classe de altura
    correspondente acima da media da peca. E medida crua — nao nomeia
    acorde, so diz qual nota subiu e qual desceu.
    """
    p = perfil / max(perfil.sum(), 1e-9)
    g = global_ / max(global_.sum(), 1e-9)
    d = p - g
    sobe = np.argsort(d)[::-1][:n]
    desce = np.argsort(d)[:n]
    return ("+" + " +".join(f"{NOTAS[i]}{d[i] * 100:+.1f}" for i in sobe if d[i] > 0),
            " ".join(f"{NOTAS[i]}{d[i] * 100:+.1f}" for i in desce if d[i] < 0))


def casa_sequencia(seq, campo, tempos, ini, fim, exclui):
    """Desliza a sequencia de croma do bloco sobre a peca inteira.

    Mais discriminante que comparar perfis medios: dois blocos na mesma
    tonalidade tem perfil medio parecido mesmo sendo secoes diferentes, e e
    por isso que o perfil medio empata tanto. Aqui entra a ORDEM.

    Devolve os tres melhores casamentos fora da vizinhanca do proprio bloco,
    para que a separacao entre o 1o e o 2o possa ser lida.
    """
    L = seq.shape[1]
    n = campo.shape[1]
    if L < 2 or n <= L:
        return []
    val = np.array([float(np.mean(np.sum(seq * campo[:, s:s + L], axis=0)))
                    for s in range(n - L + 1)])
    cand = sorted(((float(val[s]), float(tempos[s])) for s in range(len(val))
                   if abs(tempos[s] - ini) > exclui), reverse=True)
    melhores = []
    for v, t in cand:
        if all(abs(t - tb) > exclui for _, tb in melhores):
            melhores.append((v, t))
        if len(melhores) == 3:
            break
    return melhores


def julga_tonal(sep):
    if sep >= SEP_TONAL_OK:
        return "confiavel"
    return "fraco" if sep >= SEP_TONAL_FRACA else "INCONCLUSIVO"


# ---------------------------------------------------------------------------
# Linha de comando
# ---------------------------------------------------------------------------
ap = argparse.ArgumentParser(
    description="Mede fronteiras de secao, centro tonal e repeticao num trecho musical.")
ap.add_argument("entrada", help="arquivo de midia (mp4, wav, ...)")
ap.add_argument("--inicio", type=float, default=0.0,
                help="segundos dentro da entrada onde o trecho comeca (padrao 0)")
ap.add_argument("--dur", type=float, default=None,
                help="duracao do trecho em segundos (padrao: ate o fim)")
ap.add_argument("--destino", default=None,
                help="prefixo das saidas; padrao work/<base>")
ap.add_argument("--kernels", default=KERNELS,
                help=f"tamanhos do checkerboard em tempos (padrao {KERNELS})")
ap.add_argument("--min-compassos", type=float, default=MIN_COMPASSOS,
                help=f"secao minima, em compassos (padrao {MIN_COMPASSOS})")
ap.add_argument("--tol-compassos", type=float, default=TOL_COMPASSOS,
                help=f"tolerancia de concordancia, em compassos (padrao {TOL_COMPASSOS})")
ap.add_argument("--delta", type=float, default=DELTA_PICO,
                help=f"piso do pico como fracao do maximo (padrao {DELTA_PICO})")
ap.add_argument("--estabilidade", type=float, default=ESTABILIDADE,
                help=f"fracao dos kernels que precisa concordar (padrao {ESTABILIDADE})")
ap.add_argument("--compasso", type=int, default=COMPASSO,
                help=f"tempos por compasso (padrao {COMPASSO})")
ap.add_argument("--bpm", type=float, default=None,
                help="forca o andamento em vez de rastrear")
ap.add_argument("--sem-figura", action="store_true")
args = ap.parse_args()

entrada = pathlib.Path(args.entrada).expanduser().resolve()
if not entrada.exists():
    sys.exit(f"nao encontrado: {entrada}")
kernels = sorted({int(x) for x in args.kernels.split(",") if x.strip()})
if not kernels:
    sys.exit("--kernels vazio")

# raiz do projeto = o primeiro ancestral que tenha um work/. Sobreviver a
# reorganizacao de out/ em subpastas por episodio custa tres linhas.
raiz = next((a for a in entrada.parents if (a / "work").is_dir()), entrada.parent)
destino = pathlib.Path(args.destino).expanduser() if args.destino \
    else raiz / "work" / entrada.stem
destino.parent.mkdir(parents=True, exist_ok=True)
tsv_saida = pathlib.Path(str(destino) + ".secoes.tsv")
png_saida = pathlib.Path(str(destino) + ".secoes.png")

import librosa  # noqa: E402  (import pesado; so depois de validar os argumentos)

tmp = pathlib.Path(tempfile.mkdtemp(prefix="secoes-"))
try:
    wav = tmp / "trecho.wav"
    extrai_wav(entrada, args.inicio, args.dur, wav, SR)
    y, sr = librosa.load(str(wav), sr=SR, mono=True)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

dur = len(y) / sr
P = print
P(f"\n=== Secoes: {entrada.name} ===")
P(f"trecho              {args.inicio:.3f}s -> {args.inicio + dur:.3f}s da origem")
P(f"duracao analisada   {dur:.3f}s @ {sr} Hz mono, hop {HOP} ({1000 * HOP / sr:.1f} ms)")
P(f"REFERENCIAL         todos os tempos abaixo sao RELATIVOS ao trecho: "
  f"0.000 = {args.inicio:.3f}s de {entrada.name}")

# ---------------------------------------------------------------------------
# 1. Andamento e grade
# ---------------------------------------------------------------------------
onset = librosa.onset.onset_strength(y=y, sr=sr, hop_length=HOP)
bpm_rast, quadros_tempo = librosa.beat.beat_track(
    onset_envelope=onset, sr=sr, hop_length=HOP, trim=False,
    start_bpm=args.bpm or 120.0, units="frames")
bpm = float(args.bpm or np.atleast_1d(bpm_rast)[0])
t_tempos = librosa.frames_to_time(quadros_tempo, sr=sr, hop_length=HOP)
dur_compasso = args.compasso * 60.0 / bpm
min_secao = args.min_compassos * dur_compasso
tol = args.tol_compassos * dur_compasso

# Fase do compasso, medida de duas maneiras independentes:
#   (a) ataque — qual dos tempos carrega mais energia de onset;
#   (b) mudanca harmonica — em qual tempo o croma mais muda em relacao ao
#       anterior. Em violao solo o (b) costuma ser o que decide, porque o
#       acorde troca no tempo forte, enquanto o ataque mais forte pode cair
#       em qualquer lugar do padrao de dedilhado.
# O script fica com o estimador que tiver MAIS SEPARACAO e avisa quando os
# dois discordam — fase e a medida mais fragil desta analise.
def melhor_fase(serie, n_fases):
    ordem = sorted(((float(serie[p::n_fases].mean()), p) for p in range(n_fases)),
                   reverse=True)
    f1, f2 = ordem[0][0], ordem[1][0]
    return ordem[0][1], (f1 - f2) / max(abs(f1), 1e-9), ordem


forca = onset[np.clip(quadros_tempo, 0, len(onset) - 1)]
fase_atq, sep_atq, ord_atq = melhor_fase(forca, args.compasso)

# Segunda opiniao sobre o andamento: autocorrelacao do envelope de ataque.
# Se o pico do lag de 1 compasso nao se separar dos vizinhos, a grade e chute.
o = onset - onset.mean()
acf = np.correlate(o, o, mode="full")[len(o) - 1:]
acf = acf / max(acf[0], 1e-12)
lag_s = np.arange(len(acf)) * HOP / sr
sel = np.where((lag_s > 0.3) & (lag_s < 4.0))[0]
pk_acf = sorted(((acf[i], lag_s[i]) for i in sel[1:-1]
                 if acf[i] > acf[i - 1] and acf[i] > acf[i + 1]), reverse=True)

ibi = np.diff(t_tempos)
P()
P("--- 1. andamento e grade ---")
P(f"BPM                 {bpm:.2f}  ({len(t_tempos)} tempos, "
  f"intervalo mediano {float(np.median(ibi)) * 1000:.1f} ms, "
  f"desvio {float(np.std(ibi)) * 1000:.1f} ms)")
P("autocorrelacao do envelope de ataque, 5 maiores lags entre 0,3 e 4,0s:")
for v, lg in pk_acf[:5]:
    marca = ""
    for n in (1, 2, 3, 4, 6, 8):
        if abs(lg - n * 60.0 / bpm) < 0.05:
            marca = f"= {n} tempo(s)" + (" = 1 COMPASSO" if n == args.compasso else "")
    P(f"  lag {lg:6.3f}s  r={v:.3f}  {marca}")

# ---------------------------------------------------------------------------
# 2. Fronteiras: varredura de escala em duas familias de descritor
# ---------------------------------------------------------------------------
croma = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=HOP,
                                   bins_per_octave=BINS_OITAVA)
mfcc = librosa.feature.mfcc(y=y, sr=sr, hop_length=HOP, n_mfcc=20)[1:]

croma_b = librosa.util.sync(croma, quadros_tempo, aggregate=np.median)
mfcc_b = librosa.util.sync(mfcc, quadros_tempo, aggregate=np.mean)
t_b = t_tempos
if croma_b.shape[1] == len(quadros_tempo) + 1:   # librosa.sync abre uma borda
    t_b = np.concatenate([[0.0], t_tempos])
t_b = t_b[:croma_b.shape[1]]

# fase (b): mudanca harmonica entre tempos consecutivos, alinhada ao tempo
# em que a mudanca CHEGA — mudanca[i] compara o tempo i com o i-1.
xn = croma_b / np.maximum(np.linalg.norm(croma_b, axis=0, keepdims=True), 1e-9)
mudanca = np.concatenate([[0.0], np.linalg.norm(np.diff(xn, axis=1), axis=0)])
fase_harm, sep_harm, ord_harm = melhor_fase(mudanca[1:], args.compasso)
fase_harm = (fase_harm + 1) % args.compasso   # desfaz o descarte do 1o tempo

if sep_harm >= sep_atq:
    fase, sep_fase, origem_fase = fase_harm, sep_harm, "mudanca harmonica"
else:
    fase, sep_fase, origem_fase = fase_atq, sep_atq, "ataque"
t_compassos = t_tempos[fase::args.compasso]

P()
P(f"--- fase do tempo forte ({args.compasso} candidatos) ---")
P(f"  por ataque             fase {fase_atq}, separacao {100 * sep_atq:5.1f}%  "
  + " ".join(f"[{p}]{v:.3f}" for v, p in sorted(ord_atq, key=lambda z: z[1])))
P(f"  por mudanca harmonica  fase {fase_harm}, separacao {100 * sep_harm:5.1f}%  "
  + " ".join(f"[{(p + 1) % args.compasso}]{v:.3f}"
             for v, p in sorted(ord_harm, key=lambda z: z[1])))
P(f"  adotada: {origem_fase} (fase {fase}, {len(t_compassos)} tempos fortes)")
if fase_atq != fase_harm:
    P(f"  ATENCAO: os dois estimadores discordam em "
      f"{abs(fase_atq - fase_harm)} tempo(s) = "
      f"{abs(fase_atq - fase_harm) * 60 / bpm * 1000:.0f} ms. A fase do tempo "
      f"forte carrega essa incerteza; o numero confiavel e o desvio ao TEMPO.")
if sep_fase < 0.10:
    P("  separacao abaixo de 10%: a fase e chute. Use o desvio ao TEMPO.")

ssm_croma, ssm_mfcc = similaridade(croma_b), similaridade(mfcc_b)
borda = 1.0 * dur_compasso   # picos colados na borda sao artefato do padding

familias = {"croma": ssm_croma, "mfcc": ssm_mfcc}
curvas = {}
brutos = {"croma": [], "mfcc": []}
P()
P(f"--- 2. fronteiras: varredura de escala "
  f"(kernels {kernels} tempos = "
  f"{', '.join(f'{k * 60 / bpm:.1f}s' for k in kernels)}) ---")
P(f"secao minima {min_secao:.2f}s ({args.min_compassos:g} compassos), "
  f"piso {args.delta:.2f} do maximo, tolerancia {tol:.2f}s "
  f"({args.tol_compassos:g} compasso)")
for fam, ssm in familias.items():
    for k in kernels:
        c = novidade(ssm, max(2, k))
        curvas[(fam, k)] = c
        ps = [(t, a) for t, a in picos(c, t_b, min_secao, args.delta)
              if borda < t < dur - borda]
        brutos[fam] += [(t, a, k) for t, a in ps]
        P(f"  {fam:5s} k={k:2d}  " + "  ".join(f"{t:6.2f}({a:.2f})" for t, a in ps))

# leitura de controle: janela fixa, independente do rastreador de tempos
passo = max(1, int(round(JANELA_FIXA * sr / HOP)))
n_fix = croma.shape[1] // passo
croma_f = np.stack([croma[:, i * passo:(i + 1) * passo].mean(axis=1)
                    for i in range(n_fix)], axis=1)
t_f = np.arange(n_fix) * passo * HOP / sr
nov_fixo = novidade(similaridade(croma_f),
                    max(2, int(round(KERNEL_FIXO / JANELA_FIXA / 2))))
picos_fixo = [(t, a) for t, a in picos(nov_fixo, t_f, min_secao, args.delta)
              if borda < t < dur - borda]
P(f"  croma em janela fixa de {JANELA_FIXA:.0f}s, kernel {KERNEL_FIXO:.0f}s "
  f"(controle, sem rastreador de tempos):")
P("         " + "  ".join(f"{t:6.2f}({a:.2f})" for t, a in picos_fixo))


def consolida(itens, n_escalas):
    """Agrupa picos de varias escalas e mede a estabilidade de cada fronteira."""
    saida = []
    for g in agrupa(itens, tol):
        ks = {k for _, _, k in g}
        alturas = [a for _, a, _ in g]
        # posicao = a da escala mediana, nao a media: evita puxar a fronteira
        # para o lado da escala que dispara pico duplicado
        pos = float(np.median([t for t, _, _ in g]))
        pos = min((t for t, _, _ in g), key=lambda t: abs(t - pos))
        saida.append((pos, len(ks) / n_escalas, float(np.mean(alturas)), sorted(ks)))
    return saida


cons_croma = consolida(brutos["croma"], len(kernels))
cons_mfcc = consolida(brutos["mfcc"], len(kernels))

P()
P(f"--- estabilidade por familia (fracao das {len(kernels)} escalas) ---")
for fam, cons in (("croma", cons_croma), ("mfcc", cons_mfcc)):
    for t, est, alt, ks in cons:
        P(f"  {fam:5s} {t:6.2f}s  estabilidade {est:.2f} ({len(ks)}/{len(kernels)}) "
          f"altura media {alt:.2f}  kernels {ks}")

# fronteira aceita = a familia harmonica a acha em pelo menos `estabilidade`
# das escalas. Croma manda porque a legenda a montar e de harmonia.
aceitas = [c for c in cons_croma if c[1] >= args.estabilidade]

fronteiras = []
for t, est, alt, ks in aceitas:
    d_mfcc = min(((abs(t - tm), tm) for tm, _, _, _ in cons_mfcc),
                 default=(float("inf"), None))
    d_fix = min((abs(t - tf) for tf, _ in picos_fixo), default=float("inf"))
    concorda = []
    if d_mfcc[0] <= tol:
        concorda.append("mfcc")
    if d_fix <= tol:
        concorda.append("croma-1s")
    if d_mfcc[0] <= tol:
        forca_f = "FORTE"
    elif d_mfcc[0] <= 2 * tol:
        forca_f = "media"
    else:
        forca_f = "fraca"
    fronteiras.append(dict(t=t, est=est, alt=alt, forca=forca_f,
                           d_mfcc=d_mfcc[0], t_mfcc=d_mfcc[1], d_fix=d_fix,
                           concorda=concorda))

P()
P(f"--- fronteiras aceitas (estabilidade >= {args.estabilidade:.2f} no croma) ---")
P("  FORTE = o MFCC (timbre) tambem acha, dentro de 1 compasso")
P("  media = o MFCC acha, mas deslocado de 1 a 2 compassos")
P("  fraca = so o croma acha")
for f in fronteiras:
    dm = "-" if f["t_mfcc"] is None else f"{f['t_mfcc']:.2f}s (+{f['d_mfcc']:.2f}s)"
    df = "-" if not np.isfinite(f["d_fix"]) else f"{f['d_fix']:.2f}s"
    P(f"  {f['t']:6.2f}s  {f['forca']:5s}  estab {f['est']:.2f}  "
      f"mfcc mais proximo {dm:22s} croma-1s {df}")

# ---------------------------------------------------------------------------
# 3. Desvio para a grade
# ---------------------------------------------------------------------------
P()
P("--- 3. desvio de cada fronteira para a grade ---")
for f in fronteiras:
    f["d_tempo"] = float(np.min(np.abs(t_tempos - f["t"]))) if len(t_tempos) else np.nan
    f["d_comp"] = float(np.min(np.abs(t_compassos - f["t"]))) if len(t_compassos) else np.nan
    f["fase"] = int(np.argmin(np.abs(t_tempos - f["t"]))) % args.compasso \
        if len(t_tempos) else -1
    P(f"  {f['t']:6.2f}s  ao tempo {f['d_tempo'] * 1000:6.1f} ms  |  "
      f"ao tempo forte {f['d_comp'] * 1000:6.1f} ms "
      f"({f['d_comp'] / dur_compasso:.2f} compasso)  |  cai na fase {f['fase']}")

# As fronteiras caem todas na mesma fase da grade? Se caem, isso e evidencia
# forte por si so: com `compasso` fases e n fronteiras independentes, a
# chance de coincidirem por acaso e compasso^-(n-1). E, sendo o comeco de
# secao um tempo forte por definicao, essa fase e o melhor palpite do
# tempo forte — melhor que os dois estimadores de sinal, que discordam.
if fronteiras:
    from collections import Counter
    cont = Counter(f["fase"] for f in fronteiras)
    fase_dom, n_dom = cont.most_common(1)[0]
    n_tot = len(fronteiras)
    P(f"  fronteiras na mesma fase: {n_dom}/{n_tot} (fase {fase_dom})  "
      f"— chance por acaso {args.compasso ** -(n_tot - 1):.4f}")
    if n_dom == n_tot and n_tot >= 3:
        P(f"  as {n_tot} fronteiras concordam entre si. Como inicio de secao e "
          f"tempo forte por definicao, a fase {fase_dom} e o melhor palpite do")
        P(f"  tempo forte — e vence os dois estimadores de sinal "
          f"(ataque: {fase_atq}, mudanca harmonica: {fase_harm}).")

# ---------------------------------------------------------------------------
# 4. Blocos: centro tonal e repeticao
# ---------------------------------------------------------------------------
cortes = [0.0] + [f["t"] for f in fronteiras] + [dur]
blocos = [(cortes[i], cortes[i + 1]) for i in range(len(cortes) - 1)]

perfis, tonais = [], []
for ini, fim in blocos:
    i0 = int(ini * sr / HOP)
    i1 = max(i0 + 1, int(fim * sr / HOP))
    p = croma[:, i0:i1].mean(axis=1)
    perfis.append(p)
    tonais.append(centro_tonal(p))
perfis_m = np.stack(perfis, axis=1)

croma_global = croma.mean(axis=1)
distintivas = [classes_distintivas(p, croma_global) for p in perfis]

P()
P("--- 4. centro tonal por bloco (Krumhansl-Kessler) ---")
for k, ((ini, fim), (rot, r1, rot2, r2, sep)) in enumerate(zip(blocos, tonais)):
    P(f"  B{k} {ini:6.2f}-{fim:6.2f}s ({fim - ini:5.2f}s)  {rot:9s} r={r1:.3f}  |  "
      f"2o {rot2:9s} r={r2:.3f}  sep {sep:.3f}  {julga_tonal(sep)}")
P()
P("--- classes de altura que distinguem cada bloco da peca inteira ---")
P("    (desvio do perfil do bloco para o perfil global, em pontos percentuais;")
P("     e onde a modulacao aparece antes de aparecer no rotulo de tonalidade)")
for k, (sobe, desce) in enumerate(distintivas):
    P(f"  B{k}  sobe {sobe:34s}  desce {desce}")

sim = similaridade(perfis_m)
P()
P("--- repeticao entre blocos (cosseno dos perfis de croma) ---")
P("        " + " ".join(f"  B{j} " for j in range(len(blocos))))
for i in range(len(blocos)):
    P(f"    B{i}  " + " ".join(f"{sim[i, j]:+.2f}" for j in range(len(blocos))))
P()
pares = []
for i in range(len(blocos)):
    outros = sorted(((sim[i, j], j) for j in range(len(blocos)) if j != i),
                    reverse=True)
    s1, j1 = outros[0]
    s2 = outros[1][0] if len(outros) > 1 else -1.0
    pares.append((i, j1, s1, s2, s1 - s2))
    julg = "claro" if s1 - s2 >= SEP_REPET_OK else "INCONCLUSIVO (empate com o 2o)"
    P(f"  B{i} mais parecido com B{j1}: {s1:+.3f}  "
      f"(2o melhor {s2:+.3f}, sep {s1 - s2:+.3f})  {julg}")

rotulos = [""] * len(blocos)
letras = "ABCDEFGHIJKL"
prox = 0
for i in range(len(blocos)):
    if rotulos[i]:
        continue
    rotulos[i] = letras[prox]
    n = 0
    for j in range(i + 1, len(blocos)):
        if not rotulos[j] and sim[i, j] >= LIM_GRUPO:
            n += 1
            rotulos[j] = letras[prox] + "'" * n
    prox += 1
P()
P(f"--- agrupamento (limiar de cosseno {LIM_GRUPO:.2f}) ---")
P("  " + "   ".join(f"B{i}={r}" for i, r in enumerate(rotulos)))

# Casamento de sequencia: mais discriminante que o perfil medio, porque
# leva a ORDEM em conta. Dois blocos na mesma tonalidade tem perfil medio
# parecido mesmo sendo secoes diferentes — e por isso que o perfil medio
# empata tanto acima.
passo_seq = max(1, int(round(0.25 * sr / HOP)))
n_seq = croma.shape[1] // passo_seq
campo = np.stack([croma[:, i * passo_seq:(i + 1) * passo_seq].mean(axis=1)
                  for i in range(n_seq)], axis=1)
campo = campo - campo.mean(axis=0, keepdims=True)
campo = campo / np.maximum(np.linalg.norm(campo, axis=0, keepdims=True), 1e-9)
t_seq = np.arange(n_seq) * passo_seq * HOP / sr

P()
P("--- repeticao por casamento de sequencia (croma a 0,25s, leva a ordem em conta) ---")
casamentos = []
for k, (ini, fim) in enumerate(blocos):
    i0, i1 = int(ini / (passo_seq * HOP / sr)), int(fim / (passo_seq * HOP / sr))
    i1 = min(i1, n_seq)
    melhores = casa_sequencia(campo[:, i0:i1], campo, t_seq, ini, fim,
                              0.5 * (fim - ini))
    casamentos.append(melhores)
    if not melhores:
        P(f"  B{k}  bloco curto demais para deslizar")
        continue
    linha = "  ".join(f"{t:6.2f}s({v:+.3f})" for v, t in melhores)
    if len(melhores) >= 2:
        sep = melhores[0][0] - melhores[1][0]
        julg = "claro" if sep >= 0.05 else "INCONCLUSIVO"
    else:
        sep, julg = float("nan"), "unico candidato"
    P(f"  B{k} {ini:6.2f}-{fim:6.2f}s casa em: {linha}   sep {sep:+.3f}  {julg}")

# Reincidencia do perfil tonal. Para cada bloco, correlaciona a tonalidade
# que ele venceu contra uma janela deslizante sobre a peca inteira e pergunta
# onde mais aquele centro tonal aparece. E a medida que responde "essa secao
# volta?" sem depender de casar a sequencia inteira — uma modulacao curta
# reaparece aqui mesmo quando o resto da secao foi tocado diferente.
jan_tr = args.min_compassos * dur_compasso
t_tr, perfis_tr = [], []
t0 = 0.0
while t0 + jan_tr <= dur:
    i0, i1 = int(t0 * sr / HOP), int((t0 + jan_tr) * sr / HOP)
    perfis_tr.append(croma[:, i0:i1].mean(axis=1))
    t_tr.append(t0 + jan_tr / 2)
    t0 += dur_compasso / 2
t_tr = np.array(t_tr)


def trajetoria(rot):
    i = NOTAS.index(rot.split()[0])
    q = np.roll(KK_MAIOR if rot.endswith("maior") else KK_MENOR, i)
    q = q - q.mean()
    nq = np.linalg.norm(q)
    saida = []
    for v in perfis_tr:
        vv = v - v.mean()
        saida.append(float(vv @ q / max(np.linalg.norm(vv) * nq, 1e-9)))
    return np.array(saida)


P()
P(f"--- reincidencia do perfil tonal (janela {jan_tr:.1f}s, passo meio compasso) ---")
P("    onde mais, fora do proprio bloco, o centro tonal daquele bloco aparece")
trajetorias = {}
for k, ((ini, fim), (rot, *_)) in enumerate(zip(blocos, tonais)):
    if rot not in trajetorias:
        trajetorias[rot] = trajetoria(rot)
    tr = trajetorias[rot]
    dentro = (t_tr >= ini) & (t_tr < fim)
    fora = ~dentro
    if not dentro.any() or not fora.any():
        continue
    i_d = int(np.argmax(np.where(dentro, tr, -9)))
    i_f = int(np.argmax(np.where(fora, tr, -9)))
    P(f"  B{k} {rot:9s} pico dentro {tr[i_d]:+.3f} em {t_tr[i_d]:6.2f}s  |  "
      f"maior fora {tr[i_f]:+.3f} em {t_tr[i_f]:6.2f}s  "
      f"(lag {t_tr[i_f] - t_tr[i_d]:+7.2f}s, "
      f"{100 * tr[i_f] / max(tr[i_d], 1e-9):5.1f}% do pico)")

# periodo global de repeticao: media das diagonais da SSM.
# Aqui e onde o oficina-g3 mordeu — se os candidatos nao se separam, o
# periodo e inconclusivo e o script diz isso.
n_b = ssm_croma.shape[0]
diag = np.array([float(np.mean(np.diagonal(ssm_croma, k))) for k in range(n_b)])
lag_b = t_b - t_b[0]
sel = np.where((lag_b > 2 * dur_compasso) & (lag_b < 0.75 * dur))[0]
pk_diag = sorted(((diag[i], lag_b[i]) for i in sel[1:-1]
                  if diag[i] > diag[i - 1] and diag[i] > diag[i + 1]), reverse=True)
P()
P("--- periodo global de repeticao (media das diagonais da SSM) ---")
for v, lg in pk_diag[:5]:
    P(f"  lag {lg:6.2f}s  sim={v:+.3f}")
if len(pk_diag) >= 2:
    s = pk_diag[0][0] - pk_diag[1][0]
    P(f"  separacao 1o-2o: {s:+.3f}  "
      + ("-> periodo global INCONCLUSIVO: musica repetitiva casa consigo "
         "mesma em varios lags (ver oficina-g3 no CLAUDE.md)"
         if s < 0.03 else "-> candidato destacado"))

# ---------------------------------------------------------------------------
# TSV
# ---------------------------------------------------------------------------
with tsv_saida.open("w", encoding="utf-8") as f:
    w = f.write
    w(f"# secoes musicais — fonte: {entrada.name}\n")
    w(f"# trecho analisado: {args.inicio:.3f}s a {args.inicio + dur:.3f}s "
      f"do arquivo de origem ({dur:.3f}s)\n")
    w("# REFERENCIAL DE TEMPO: as colunas inicio/fim sao RELATIVAS ao inicio\n")
    w(f"#   do trecho. 0.000 aqui = {args.inicio:.3f}s em {entrada.name}.\n")
    w(f"# grade: BPM {bpm:.2f}, compasso {args.compasso}/4 = {dur_compasso:.3f}s, "
      f"fase {fase} por {origem_fase} (separacao {100 * sep_fase:.1f}%"
      + ("; o outro estimador discorda" if fase_atq != fase_harm else "") + ")\n")
    w(f"# metodo: novidade de Foote sobre auto-similaridade, varrida em "
      f"{len(kernels)} escalas ({','.join(str(k) for k in kernels)} tempos),\n")
    w("#   em duas familias de descritor: croma (harmonia) e MFCC (timbre),\n")
    w(f"#   mais um controle em janela fixa de {JANELA_FIXA:.0f}s.\n")
    w("# colunas:\n")
    w("#   inicio, fim   mm:ss.mmm relativos ao trecho\n")
    w("#   dur_s         duracao do bloco\n")
    w("#   rotulo        agrupamento por similaridade de croma (A, A', B...)\n")
    w("#   tonal         centro tonal estimado (Krumhansl-Kessler)\n")
    w("#   r             correlacao do melhor candidato\n")
    w("#   sep_tonal     r do melhor menos r do 2o de OUTRA tonica\n")
    w(f"#   conf_tonal    confiavel >= {SEP_TONAL_OK}, fraco >= {SEP_TONAL_FRACA}, "
      f"senao INCONCLUSIVO\n")
    w("#   fronteira     forca da fronteira que ABRE o bloco:\n")
    w("#                 FORTE = croma e MFCC concordam dentro de 1 compasso\n")
    w("#                 media = MFCC concorda, deslocado de 1 a 2 compassos\n")
    w("#                 fraca = so o croma acha\n")
    w("#                 inicio = borda do trecho, nao medida\n")
    w("#   estab         fracao das escalas de kernel que acham a fronteira\n")
    w("#   concorda      metodos independentes que confirmam dentro de 1 compasso\n")
    w("#   desvio_ms     distancia da fronteira ao tempo forte mais proximo\n")
    w("#   sobe          classes de altura acima da media da peca, em pontos\n")
    w("#                 percentuais — e a evidencia crua de modulacao\n")
    w("#   casa_em       melhor casamento de sequencia fora do proprio bloco,\n")
    w("#                 com a separacao para o 2o candidato entre parenteses\n")
    w("inicio\tfim\tdur_s\trotulo\ttonal\tr\tsep_tonal\tconf_tonal\t"
      "fronteira\testab\tconcorda\tdesvio_ms\tsobe\tcasa_em\n")
    for k, ((ini, fim), (rot, r1, _r2n, _r2, sep)) in enumerate(zip(blocos, tonais)):
        if k == 0:
            marca, est, quem, dv = "inicio", "", "-", ""
        else:
            fr = fronteiras[k - 1]
            marca = fr["forca"]
            est = f"{fr['est']:.2f}"
            quem = ",".join(fr["concorda"]) or "-"
            dv = f"{fr['d_comp'] * 1000:.0f}"
        m = casamentos[k]
        if len(m) >= 2:
            casa = f"{m[0][1]:.2f}s({m[0][0]:+.3f},sep{m[0][0] - m[1][0]:+.3f})"
            if m[0][0] - m[1][0] < 0.05:
                casa += " INCONCLUSIVO"
        elif m:
            casa = f"{m[0][1]:.2f}s({m[0][0]:+.3f})"
        else:
            casa = "-"
        w(f"{hms(ini)}\t{hms(fim)}\t{fim - ini:7.3f}\t{rotulos[k]}\t{rot}\t"
          f"{r1:.3f}\t{sep:.3f}\t{julga_tonal(sep)}\t{marca}\t{est}\t{quem}\t{dv}\t"
          f"{distintivas[k][0]}\t{casa}\n")
P()
P(f"TSV: {tsv_saida}")

# ---------------------------------------------------------------------------
# Figura
# ---------------------------------------------------------------------------
if not args.sem_figura:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(5, 1, figsize=(16, 18),
                           gridspec_kw={"height_ratios": [1.2, 2.4, 1.1, 1.0, 0.6]})
    fortes = [f["t"] for f in fronteiras if f["forca"] == "FORTE"]
    medias = [f["t"] for f in fronteiras if f["forca"] == "media"]
    fracas = [f["t"] for f in fronteiras if f["forca"] == "fraca"]

    def linhas(a):
        for t in fortes:
            a.axvline(t, color="crimson", lw=2.0, alpha=0.95)
        for t in medias:
            a.axvline(t, color="crimson", lw=1.4, ls="-.", alpha=0.7)
        for t in fracas:
            a.axvline(t, color="crimson", lw=1.2, ls="--", alpha=0.55)

    tc = librosa.frames_to_time(np.arange(croma.shape[1]), sr=sr, hop_length=HOP)
    ax[0].imshow(croma, aspect="auto", origin="lower", cmap="magma",
                 extent=[tc[0], tc[-1], 0, 12], interpolation="nearest")
    ax[0].set_yticks(np.arange(12) + 0.5)
    ax[0].set_yticklabels(NOTAS, fontsize=8)
    ax[0].set_title(f"Cromagrama CQT — {entrada.name}   "
                    f"[{args.inicio:.1f}s a {args.inicio + dur:.1f}s da origem; "
                    f"eixo relativo ao trecho]   BPM {bpm:.1f}, "
                    f"compasso {dur_compasso:.3f}s")
    linhas(ax[0])
    for k, ((ini, fim), (_r, _a, _b, _c, sep)) in enumerate(zip(blocos, tonais)):
        ax[0].text((ini + fim) / 2, 12.5,
                   f"{rotulos[k]} · {tonais[k][0]}", ha="center", fontsize=10,
                   color="black" if sep >= SEP_TONAL_FRACA else "0.55")
    ax[0].set_xlim(0, dur)
    ax[0].set_ylim(0, 13.6)

    ax[1].imshow(ssm_croma, aspect="equal", origin="lower", cmap="viridis",
                 extent=[t_b[0], t_b[-1], t_b[0], t_b[-1]],
                 vmin=-1, vmax=1, interpolation="nearest")
    ax[1].set_title("Auto-similaridade — croma beat-sincrono (cosseno). "
                    "Quadrado claro na diagonal = bloco homogeneo; "
                    "quadrado claro fora dela = repeticao.")
    for t in fortes + medias + fracas:
        est = "-" if t in fortes else ("-." if t in medias else "--")
        ax[1].axvline(t, color="crimson", lw=1.0, ls=est, alpha=0.8)
        ax[1].axhline(t, color="crimson", lw=1.0, ls=est, alpha=0.8)
    ax[1].set_xlim(0, dur)
    ax[1].set_ylim(0, dur)

    for (fam, k), c in curvas.items():
        ax[2].plot(t_b[:len(c)], c, color="C0" if fam == "croma" else "C1",
                   lw=1.0, alpha=0.45)
    ax[2].plot(t_f[:len(nov_fixo)], nov_fixo, "C2", lw=1.2, alpha=0.8)
    ax[2].plot([], [], "C0", label=f"croma-beat ({len(kernels)} escalas)")
    ax[2].plot([], [], "C1", label=f"mfcc-beat ({len(kernels)} escalas)")
    ax[2].plot([], [], "C2", label=f"croma janela {JANELA_FIXA:.0f}s (controle)")
    ax[2].axhline(args.delta, color="gray", ls=":", lw=1,
                  label=f"piso {args.delta:.2f}")
    for f in fronteiras:
        ax[2].plot([f["t"]], [f["alt"]], "o", color="crimson", ms=6)
        ax[2].annotate(f"{f['est']:.2f}", (f["t"], f["alt"]),
                       textcoords="offset points", xytext=(4, 5), fontsize=8,
                       color="crimson")
    ax[2].set_title("Novidade de Foote — todas as escalas sobrepostas "
                    "(o numero e a estabilidade da fronteira)")
    ax[2].legend(loc="upper right", fontsize=8, ncol=4)
    linhas(ax[2])
    ax[2].set_xlim(0, dur)
    ax[2].set_ylim(0, 1.05)

    # trajetoria tonal: as mesmas curvas ja medidas acima, so as tonalidades
    # que venceram algum bloco. E aqui que a modulacao se ve.
    for rot, curva_k in trajetorias.items():
        ax[3].plot(t_tr, curva_k, lw=1.6, label=rot)
    ax[3].set_title(f"Trajetoria tonal — correlacao Krumhansl-Kessler em janela "
                    f"deslizante de {jan_tr:.1f}s (passo meio compasso), so as "
                    f"tonalidades que venceram algum bloco")
    ax[3].legend(loc="lower right", fontsize=8, ncol=len(trajetorias))
    ax[3].set_ylabel("r")
    linhas(ax[3])
    ax[3].set_xlim(0, dur)

    env = np.abs(y)
    passo_env = max(1, len(env) // 2000)
    e = env[:len(env) // passo_env * passo_env].reshape(-1, passo_env).max(axis=1)
    te = np.arange(len(e)) * passo_env / sr
    ax[4].fill_between(te, 0, e, color="0.65", lw=0)
    for t in t_compassos:
        ax[4].axvline(t, color="steelblue", lw=0.6, alpha=0.45)
    linhas(ax[4])
    ax[4].set_title(f"Forma de onda + grade de compassos "
                    f"(azul: tempo forte a cada {dur_compasso:.3f}s)")
    ax[4].set_xlabel("segundos, relativos ao inicio do trecho  "
                     f"(0.000 = {args.inicio:.3f}s de {entrada.name})")
    ax[4].set_xlim(0, dur)
    ax[4].set_yticks([])

    fig.tight_layout()
    fig.savefig(png_saida, dpi=110)
    P(f"PNG: {png_saida}")
