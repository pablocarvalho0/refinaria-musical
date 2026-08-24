#!/usr/bin/env python3
"""
Passo 1 de docs/01-arquitetura-segmentacao.md.

Classifica o vídeo em regiões FALA e MUSICA a partir da transcrição e mede a
zona cinzenta. NÃO processa áudio nem corta — só produz work/segmentos.txt e
o relatório que decide se a arquitetura de segmentação se sustenta.

Entrada:  work/<base>.segments.tsv  (sidecar do transcreve.py: start, end, text)
          work/<base>.wav           (16 kHz mono, para a energia RMS)
Saída:    work/segmentos.txt

Uso: python scripts/segmenta.py work/20260824_135542.wav
"""
import argparse
import pathlib
import sys
import wave

import numpy as np

# Limiares da medição. Os dois primeiros vêm do documento ("segmentos de fala
# com menos de 2s"); o piso de silêncio é a referência usual para ruído de sala
# num áudio já normalizado a -14 LUFS.
CURTO = 2.0        # s — fala abaixo disso é suspeita de vocalização/alucinação
GAP_CURTO = 2.0    # s — buraco abaixo disso é fronteira indecidível
PISO_SILENCIO = -50.0  # dBFS — abaixo disso a região é digitalmente muda
PISO_ATIVIDADE = -35.0  # dBFS — abaixo disso não há voz nem violão soando
JANELA = 0.1       # s — resolução da análise de energia
ESTAVEL = 3.0      # s — quanto tempo acima do piso define "região assentada"


def hms(s: float) -> str:
    h, r = divmod(max(s, 0.0), 3600)
    m, seg = divmod(r, 60)
    return f"{int(h):02d}:{int(m):02d}:{seg:06.3f}"


def carrega_segmentos(tsv: pathlib.Path):
    """Lê o sidecar e funde segmentos que se sobrepõem ou se encostam."""
    bruto = []
    for i, linha in enumerate(tsv.read_text(encoding="utf-8").splitlines()):
        if i == 0 or not linha.strip():
            continue
        ini, fim, *resto = linha.split("\t")
        bruto.append((float(ini), float(fim), resto[0] if resto else ""))
    bruto.sort()

    fundidos = []
    for ini, fim, txt in bruto:
        if fundidos and ini <= fundidos[-1][1]:
            ant_i, ant_f, ant_t = fundidos[-1]
            fundidos[-1] = (ant_i, max(ant_f, fim), f"{ant_t} {txt}".strip())
        else:
            fundidos.append((ini, fim, txt))
    return fundidos


def le_wav(caminho: pathlib.Path):
    with wave.open(str(caminho), "rb") as w:
        n, sr, largura, canais = (w.getnframes(), w.getframerate(),
                                  w.getsampwidth(), w.getnchannels())
        if largura != 2:
            sys.exit(f"esperado PCM 16 bits, veio {largura * 8} bits")
        dados = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32)
    if canais > 1:
        dados = dados.reshape(-1, canais).mean(axis=1)
    return dados / 32768.0, sr


def rms_db(amostras: np.ndarray) -> float:
    """RMS em dBFS. Devolve -inf para trecho vazio ou digitalmente mudo."""
    if amostras.size == 0:
        return float("-inf")
    r = float(np.sqrt(np.mean(np.square(amostras, dtype=np.float64))))
    return 20.0 * np.log10(r) if r > 0 else float("-inf")


def fmt_db(v: float) -> str:
    return "  -inf" if v == float("-inf") else f"{v:6.1f}"


ap = argparse.ArgumentParser()
ap.add_argument("wav", help="work/<base>.wav")
ap.add_argument("--out", default=None, help="padrão: work/segmentos.txt")
args = ap.parse_args()

wav = pathlib.Path(args.wav).expanduser().resolve()
tsv = wav.with_suffix("").with_suffix(".segments.tsv") \
    if wav.suffixes[-2:] == [".segments", ".tsv"] else \
    wav.with_name(f"{wav.stem}.segments.tsv")
for f in (wav, tsv):
    if not f.exists():
        sys.exit(f"não encontrado: {f}")

audio, sr = le_wav(wav)
dur = len(audio) / sr
fala = carrega_segmentos(tsv)
if not fala:
    sys.exit("transcrição vazia — nada a classificar")

# ---------------------------------------------------------------
# Classificação: onde há texto é FALA, o complemento é MUSICA.
# ---------------------------------------------------------------
regioes = []
cursor = 0.0
for ini, fim, txt in fala:
    ini, fim = max(0.0, ini), min(dur, fim)
    if ini > cursor:
        regioes.append(["MUSICA", cursor, ini, ""])
    regioes.append(["FALA", ini, fim, txt])
    cursor = fim
if cursor < dur:
    regioes.append(["MUSICA", cursor, dur, ""])

def fatia(ini, fim):
    return audio[int(ini * sr):int(fim * sr)]

for r in regioes:
    r.append(rms_db(fatia(r[1], r[2])))

# ---------------------------------------------------------------
# work/segmentos.txt
# ---------------------------------------------------------------
destino = pathlib.Path(args.out) if args.out else wav.with_name("segmentos.txt")
with destino.open("w", encoding="utf-8") as f:
    f.write(f"# segmentacao fala/musica — fonte: {tsv.name}\n")
    f.write(f"# duracao total: {hms(dur)} ({dur:.3f}s)\n")
    f.write("# classe\tinicio\tfim\tdur_s\trms_dbfs\n")
    for classe, ini, fim, _txt, db in regioes:
        f.write(f"{classe}\t{hms(ini)}\t{hms(fim)}\t{fim - ini:8.3f}\t{fmt_db(db)}\n")

# ---------------------------------------------------------------
# Medição da seção "Medição proposta"
# ---------------------------------------------------------------
musica = [r for r in regioes if r[0] == "MUSICA"]
falas = [r for r in regioes if r[0] == "FALA"]
t_fala = sum(r[2] - r[1] for r in falas)
t_mus = sum(r[2] - r[1] for r in musica)

# Fala curta e isolada: dura menos de CURTO e tem buraco >= GAP_CURTO dos dois
# lados — ou seja, não faz parte de uma corrida contínua de fala.
def vizinho(i, passo):
    j = i + passo
    return regioes[j] if 0 <= j < len(regioes) else None

isoladas = []
for i, r in enumerate(regioes):
    if r[0] != "FALA" or (r[2] - r[1]) >= CURTO:
        continue
    ant, prox = vizinho(i, -1), vizinho(i, +1)
    g_ant = (ant[2] - ant[1]) if ant else float("inf")
    g_prox = (prox[2] - prox[1]) if prox else float("inf")
    if g_ant >= GAP_CURTO and g_prox >= GAP_CURTO:
        isoladas.append((r, g_ant, g_prox))

gaps_curtos = [r for r in musica if (r[2] - r[1]) < GAP_CURTO]
mus_mudas = [r for r in musica if r[4] < PISO_SILENCIO]

# Zona cinzenta = tudo que a transcrição sozinha não decide.
# A soma da zona cinzenta é montada depois, quando a análise de energia já
# rodou — a transição nas fronteiras é o termo que domina.

amostras_mus = np.concatenate([fatia(r[1], r[2]) for r in musica]) \
    if musica else np.array([], dtype=np.float32)

P = print
P(f"\n=== Segmentacao: {wav.name} ===")
P(f"Duracao total       {hms(dur)}  ({dur:.3f}s)")
P(f"Regioes             {len(regioes)}  ({len(falas)} FALA, {len(musica)} MUSICA)")
P()
P("--- duracao por classe ---")
P(f"FALA    {t_fala:8.3f}s  {100 * t_fala / dur:5.1f}%   em {len(falas)} regiao(oes)")
P(f"MUSICA  {t_mus:8.3f}s  {100 * t_mus / dur:5.1f}%   em {len(musica)} regiao(oes)")
P()
P("--- gaps nao cobertos por nenhum segmento de transcricao ---")
P(f"total: {len(musica)} gap(s), {t_mus:.3f}s")
for r in sorted(musica, key=lambda x: x[1] - x[2]):
    marca = []
    if (r[2] - r[1]) < GAP_CURTO:
        marca.append("curto")
    if r[4] < PISO_SILENCIO:
        marca.append("silencio")
    P(f"  {hms(r[1])} -> {hms(r[2])}  {r[2] - r[1]:8.3f}s  "
      f"rms {fmt_db(r[4])} dBFS  {' '.join(marca)}")
P(f"  abaixo de {GAP_CURTO}s: {len(gaps_curtos)} gap(s), "
  f"{sum(r[2] - r[1] for r in gaps_curtos):.3f}s")
P()
P(f"--- fala < {CURTO}s isolada dentro de regiao musical ---")
if not isoladas:
    P("  nenhuma")
for r, ga, gp in isoladas:
    P(f"  {hms(r[1])} -> {hms(r[2])}  {r[2] - r[1]:6.3f}s  "
      f"gap antes {ga:6.2f}s / depois {gp:6.2f}s  rms {fmt_db(r[4])}  \"{r[3][:60]}\"")
P()
P("--- energia RMS nas regioes MUSICA ---")
P(f"RMS agregado        {fmt_db(rms_db(amostras_mus))} dBFS")
if musica:
    dbs = [r[4] for r in musica if r[4] != float("-inf")]
    if dbs:
        P(f"por regiao          min {min(dbs):6.1f}  max {max(dbs):6.1f}  "
          f"mediana {float(np.median(dbs)):6.1f} dBFS")
P(f"regioes abaixo de {PISO_SILENCIO:.0f} dBFS (silencio mal rotulado): "
  f"{len(mus_mudas)}, {sum(r[2] - r[1] for r in mus_mudas):.3f}s")

# ---------------------------------------------------------------
# Confronto com a energia do áudio.
#
# As métricas acima só olham a transcrição olhando para si mesma: se o
# Whisper devolve segmentos encostados uns nos outros, não há gap para
# contar e a fronteira parece limpa por construção. O que decide se a
# arquitetura se sustenta é outra coisa — se o áudio corrobora o rótulo,
# e com que precisão a fronteira cai.
# ---------------------------------------------------------------
H = int(JANELA * sr)
nj = len(audio) // H
env = np.sqrt(np.mean(audio[:nj * H].reshape(nj, H).astype(np.float64) ** 2, axis=1))
env_db = np.where(env > 0, 20 * np.log10(np.maximum(env, 1e-12)), -120.0)
tj = np.arange(nj) * JANELA

rotulo_fala = np.zeros(nj, dtype=bool)
for _c, ini, fim, _txt, _db in falas:
    rotulo_fala |= (tj >= ini) & (tj < fim)
mudo = env_db < PISO_ATIVIDADE

d_fala = float(np.sum(rotulo_fala & mudo) * JANELA)   # pausa rotulada como fala
d_mus = float(np.sum(~rotulo_fala & mudo) * JANELA)   # silêncio rotulado como música

def corridas(mascara, minimo=0.5):
    saida, i = [], 0
    while i < nj:
        if mascara[i]:
            j = i
            while j < nj and mascara[j]:
                j += 1
            if (j - i) * JANELA >= minimo:
                saida.append((tj[i], tj[i] + (j - i) * JANELA))
            i = j
        else:
            i += 1
    return saida

# Zona de transição: a partir de cada fronteira, quanto tempo passa até a
# energia se assentar acima do piso por ESTAVEL segundos seguidos. É a
# margem de erro real da fronteira que a transcrição desenha.
#
# Só vale medir isso entrando numa região MUSICA. Violão soando é contínuo,
# então demora a assentar = a fronteira está no lugar errado. Fala é
# intermitente por natureza — exigir ESTAVEL segundos sem pausa mede o
# ritmo do falante, não ambiguidade, e infla o número. Fronteiras
# FALA→MUSICA entram na conta; MUSICA→FALA ficam de fora, marcadas.
n_est = int(ESTAVEL / JANELA)
fronteiras = []
for i in range(1, len(regioes)):
    b, destino_classe = regioes[i][1], regioes[i][0]
    k0 = int(b / JANELA)
    largura = 0.0
    for k in range(k0, nj - n_est):
        if np.all(env_db[k:k + n_est] > PISO_ATIVIDADE):
            largura = tj[k] - b
            break
    fronteiras.append((b, regioes[i - 1][0], destino_classe, largura))

medidas = [f for f in fronteiras if f[2] == "MUSICA"]
t_transicao = float(sum(f[3] for f in medidas))

P()
P(f"--- rotulo x energia (janelas de {JANELA * 1000:.0f}ms, piso {PISO_ATIVIDADE:.0f} dBFS) ---")
P(f"FALA rotulada mas muda (pausa dentro da fala)   {d_fala:7.2f}s  "
  f"{100 * d_fala / max(t_fala, 1e-9):5.1f}% da regiao FALA")
P(f"MUSICA rotulada mas muda (silencio, nao musica) {d_mus:7.2f}s  "
  f"{100 * d_mus / max(t_mus, 1e-9):5.1f}% da regiao MUSICA")
P(f"desacordo total                                 {d_fala + d_mus:7.2f}s  "
  f"{100 * (d_fala + d_mus) / dur:5.1f}% da duracao")
P()
P("  trechos mudos >= 0.5s dentro de MUSICA:")
for i0, i1 in corridas(~rotulo_fala & mudo):
    P(f"    {hms(i0)} -> {hms(i1)}  {i1 - i0:5.2f}s")
P("  pausas >= 0.5s dentro de FALA:")
for i0, i1 in corridas(rotulo_fala & mudo):
    P(f"    {hms(i0)} -> {hms(i1)}  {i1 - i0:5.2f}s")
P()
P(f"--- zona de transicao nas fronteiras (assentar {ESTAVEL:.0f}s acima do piso) ---")
for b, de, para, w in fronteiras:
    if para == "MUSICA":
        P(f"  {hms(b)}  {de}->{para}   {w:5.2f}s de ambiguidade")
    else:
        P(f"  {hms(b)}  {de}->{para}   (nao medivel: fala e intermitente "
          f"por natureza; o criterio mediria o ritmo do falante)")
P(f"  {len(medidas)} fronteira(s) medivel(eis) de {len(fronteiras)}, "
  f"{t_transicao:.2f}s total, "
  f"media {t_transicao / max(len(medidas), 1):.2f}s por fronteira")
P()
P("--- zona cinzenta ---")
cinzenta = (sum(r[2] - r[1] for r in gaps_curtos)
            + sum(r[2] - r[1] for r, _, _ in isoladas)
            + sum(r[2] - r[1] for r in mus_mudas if (r[2] - r[1]) >= GAP_CURTO)
            + t_transicao)
pct = 100.0 * cinzenta / dur
P(f"gaps < {GAP_CURTO}s                         "
  f"{sum(r[2] - r[1] for r in gaps_curtos):8.3f}s")
P(f"fala < {CURTO}s isolada em musica      "
  f"{sum(r[2] - r[1] for r, _, _ in isoladas):8.3f}s")
P(f"MUSICA que e silencio (>= {GAP_CURTO}s)     "
  f"{sum(r[2] - r[1] for r in mus_mudas if (r[2] - r[1]) >= GAP_CURTO):8.3f}s")
P(f"transicao nas fronteiras           {t_transicao:8.3f}s")
P(f"TOTAL                             {cinzenta:8.3f}s  = {pct:.1f}% da duracao")
P()
P(f"criterio do documento: {'ABAIXO' if pct < 10 else 'ACIMA'} de ~10% -> "
  f"{'arquitetura se sustenta com regra de desempate simples' if pct < 10 else 'exige sinal complementar'}")
P()
P("--- extrapolacao: o custo e por fronteira, nao por minuto ---")
media_tr = t_transicao / max(len(medidas), 1)
if media_tr > 0:
    orcamento = 0.10 * dur / media_tr
    P(f"a {media_tr:.2f}s de ambiguidade por fronteira, o orcamento de 10% cabe em "
      f"{orcamento:.1f} fronteira(s)")
    P(f"ou seja: uma alternancia fala/musica a cada {dur / max(orcamento, 1e-9):.0f}s ou "
      f"mais espacada")
    P(f"este episodio tem {len(fronteiras)} fronteira(s) em {dur:.0f}s "
      f"(uma a cada {dur / max(len(fronteiras), 1):.0f}s) — "
      f"amostra de {len(medidas)} fronteira(s) medivel(eis)")
P(f"\nsegmentos.txt: {destino}")
