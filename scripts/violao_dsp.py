#!/usr/bin/env python3
"""Tratamento de audio para violao solo instrumental.

Chamado pelo scripts/violao.sh. Le um WAV, escreve um WAV. Nao mexe em
video, nao chama ffmpeg, nao adivinha caminho nenhum.

A cadeia, e por que cada elo esta aqui — todos os numeros foram medidos
no trecho de 60,7 s de improviso_3 em 05/09/2026, n=120 ataques:

  1. HPF 70 Hz      Abaixo de 95 Hz nao ha nota tocada; o que existe entre
                    45 e 95 Hz e ruido de manuseio a -63 dB. O corte remove
                    1,07% da energia (0,047 dB) e nao mexe em mais nada.

  2. Rider           E ele que "corrige erro de volume". Ganho lento tirado
                    da propria short-term loudness, teto de +-3 dB, suavizado
                    em 2 s: a variacao maxima fica em 2,3 dB/s, ou 0,23 dB a
                    cada 100 ms. Ele nivela TRECHO contra TRECHO e nao encosta
                    em nota contra nota — medido, a profundidade do dedilhado
                    dentro de janelas de 4 s nao cai (+0,20 dB) e o tempo de
                    subida dos ataques nao muda (0,00 ms).

                    Um compressor faz o mesmo nivelamento e cobra caro por
                    ele: -18 dB / 3:1 entrega a mesma reducao de faixa
                    (-1,63 LU contra -1,76) mas achata o dedilhado em
                    7,66 dB e encurta o ataque em 4,96 ms. E o erro que o
                    CLAUDE.md ja registrou com o loudnorm dinamico, por
                    outro caminho. Por isso NAO ha compressor aqui.

  3. Reverb         Convolucao com uma IR sintetizada aqui mesmo, semente
                    fixa: impulso direto na amostra 0 (latencia zero por
                    construcao), reflexoes iniciais esparsas e cauda de
                    ruido decaindo com absorcao de agudos progressiva.
                    Escolhida contra o Freeverb do pedalboard e contra o
                    aecho do ffmpeg — ver o cabecalho do violao.sh.

  4. Ganho + limite Ganho estatico ate o alvo de LUFS, depois um limitador
                    de pico verdadeiro. Nao ha loudnorm: o material precisa
                    de -2,0 dB para chegar a -14 LUFS e o pico ficaria em
                    +0,54 dBTP, ou seja, nao cabe no teto e o loudnorm cairia
                    no modo dinamico — exatamente o que o projeto evita.
                    O limitador toca 0,27% das amostras, tira no maximo
                    1,54 dB e nao mexe em ataque, brilho nem dedilhado
                    (0,00 nas tres medidas).

Nao ha denoise. Medido: nao existe piso de ruido para remover (as janelas
mais quietas ficam de 37 a 57 dB abaixo do espectro medio em toda banda
acima de 120 Hz), e o afftdn=nr=10:nf=-30 do audio.sh tira 2,60 +- 0,29 dB
de energia acima de 4 kHz nos ataques. Num dedilhado, isso e a unha.
"""

import argparse
import sys

import numpy as np
import soundfile as sf
from scipy import signal
from scipy.ndimage import minimum_filter1d

SR_ESPERADO = 48000


# ------------------------------------------------------------------ medida
# Filtro K do BS.1770-4, coeficientes de 48 kHz. Conferido contra o
# ebur128 do ffmpeg no mesmo arquivo: I -11,65 contra -11,7, LRA 4,39
# contra 4,4, TP 0,12 contra 0,1.
_B1 = np.array([1.53512485958697, -2.69169618940638, 1.19839281085285])
_A1 = np.array([1.0, -1.69065929318241, 0.73248077421585])
_B2 = np.array([1.0, -2.0, 1.0])
_A2 = np.array([1.0, -1.99004745483398, 0.99007225036621])


def _k(x):
    return signal.lfilter(_B2, _A2, signal.lfilter(_B1, _A1, x, axis=0), axis=0)


def _blocos(x, sr, win, hop):
    p = _k(x) ** 2
    n, h = int(round(win * sr)), int(round(hop * sr))
    if len(p) < n:
        return np.array([]), np.array([])
    c = np.concatenate([np.zeros((1, p.shape[1])), np.cumsum(p, axis=0)])
    i = np.arange(0, len(p) - n + 1, h)
    m = (c[i + n] - c[i]) / n
    g = np.array([1.0, 1.0, 1.0, 1.41, 1.41])[: x.shape[1]]
    z = (m * g).sum(axis=1)
    with np.errstate(divide="ignore"):
        return i / sr + win / 2, z


def loudness(x, sr, win=3.0, hop=0.100):
    t, z = _blocos(x, sr, win, hop)
    with np.errstate(divide="ignore"):
        return t, -0.691 + 10 * np.log10(np.maximum(z, 1e-20))


def integrado(x, sr):
    """LUFS integrado com o gating em duas etapas do BS.1770."""
    _, z = _blocos(x, sr, 0.400, 0.100)
    with np.errstate(divide="ignore"):
        l = -0.691 + 10 * np.log10(np.maximum(z, 1e-20))
    abs_ = l > -70
    if not abs_.any():
        return float("nan")
    rel = -0.691 + 10 * np.log10(z[abs_].mean()) - 10
    sel = abs_ & (l > rel)
    return float(-0.691 + 10 * np.log10(z[sel].mean()))


def truepeak(x, sr, os=4):
    up = signal.resample_poly(x, os, 1, axis=0)
    return float(20 * np.log10(np.max(np.abs(up)) + 1e-20))


def lra(x, sr):
    _, l = loudness(x, sr, 3.0, 0.100)
    v = l[l > -70]
    if len(v) < 2:
        return float("nan")
    z = 10 ** ((v + 0.691) / 10)
    g = -0.691 + 10 * np.log10(z.mean()) - 20
    v = v[v > g]
    return float(np.percentile(v, 95) - np.percentile(v, 10)) if len(v) > 1 else float("nan")


# ------------------------------------------------------------------ elos
def hpf(x, sr, fc, ordem=2):
    if fc <= 0:
        return x
    return signal.sosfilt(signal.butter(ordem, fc, "hp", fs=sr, output="sos"), x, axis=0)


def rider(x, sr, faixa=3.0, piso=8.0, suav=2.0):
    """Nivela a macro-dinamica. Devolve (sinal, ganho_dB, tempos)."""
    if faixa <= 0:
        return x, np.zeros(1), np.zeros(1)
    hop = 0.100
    t, l = loudness(x, sr, 3.0, hop)
    I = integrado(x, sr)
    val = l > (I - piso)
    if not val.any():
        return x, np.zeros(len(t)), t
    g = np.clip(np.median(l[val]) - l, -faixa, faixa)
    # onde nao ha material (final de musica, pausa), o ganho congela no
    # vizinho valido — senao o rider levantaria a nota morrendo.
    i = np.arange(len(g))
    g = np.interp(i, i[val], g[val])
    k = max(1, int(round(suav / hop)))
    kern = np.hanning(2 * k + 1)
    kern /= kern.sum()
    g = np.convolve(np.pad(g, k, mode="edge"), kern, mode="same")[k:-k]
    gs = np.interp(np.arange(len(x)) / sr, t, g, left=g[0], right=g[-1])
    return x * 10 ** (gs[:, None] / 20), g, t


def ir_sala(sr, rt60=1.3, predelay=0.025, difusao=0.85, damping=0.35, semente=7):
    """IR sintetica. O impulso direto fica na amostra 0, entao a convolucao
    nao introduz latencia nenhuma — nao ha o que compensar depois."""
    rng = np.random.default_rng(semente)
    n = int(rt60 * 1.6 * sr)
    pd = int(predelay * sr)
    h = np.zeros((n, 2))
    for c in (0, 1):
        for _ in range(12):
            i = pd + int(rng.uniform(0, 0.045) * sr)
            h[i, c] += rng.uniform(0.25, 0.6) * difusao * rng.choice([-1, 1])
    t = np.arange(n) / sr
    env = 10 ** (-3 * t / rt60)
    env[:pd] = 0
    cauda = rng.standard_normal((n, 2)) * env[:, None] * difusao
    lp = signal.sosfilt(signal.butter(2, 4500, "lp", fs=sr, output="sos"), cauda, axis=0)
    mist = damping * np.linspace(0, 1, n)[:, None]
    cauda = cauda * (1 - mist) + lp * mist
    h = h + cauda * 0.35
    h = signal.sosfilt(signal.butter(2, 90, "hp", fs=sr, output="sos"), h, axis=0)
    h /= np.sqrt((h**2).sum(axis=0)).mean()   # energia unitaria na parte molhada
    return h


def reverb_conv(x, sr, wet_db, rt60, predelay, semente=7):
    from scipy.signal import fftconvolve

    ir = ir_sala(sr, rt60, predelay, semente=semente)
    n = len(x)
    w = np.stack(
        [fftconvolve(x[:, c], ir[:, c % ir.shape[1]])[:n] for c in range(x.shape[1])], axis=1
    )
    return x + w * 10 ** (wet_db / 20)


def reverb_freeverb(x, sr, wet_db, room=0.45, damping=0.40):
    """Alternativa medida. Fica aqui porque a diferenca para a convolucao
    e pequena o bastante para ser questao de gosto: a mesma quantidade de
    preenchimento custa 1,27 dB de ondulacao espectral contra 1,10 da
    convolucao, e a cauda e menos densa (crest 12,1 contra 10,4 dB)."""
    from pedalboard import Pedalboard, Reverb

    pb = Pedalboard(
        [Reverb(room_size=room, damping=damping, wet_level=1.0, dry_level=0.0, width=1.0)]
    )
    w = pb(x.astype("float32").T, sr).T.astype("float64")
    # casa a energia do molhado com a do seco: assim wet_db significa a
    # mesma coisa nos dois reverbs e a comparacao a ouvido e justa.
    k = np.sqrt((x**2).mean() / max((w**2).mean(), 1e-20))
    return x + w * k * 10 ** (wet_db / 20)


def brilho(x, sr, ganho_db, fc=8000.0, Q=0.7):
    """High shelf. Fora da cadeia padrao de proposito: nao corrige defeito
    medido, e questao de gosto. +2 dB em 8 kHz rende +0,55 dB de energia
    de agudo nos ataques e custa 0,13 dB de profundidade do dedilhado."""
    if ganho_db == 0:
        return x
    A = 10 ** (ganho_db / 40)
    w0 = 2 * np.pi * fc / sr
    a = np.sin(w0) / (2 * Q)
    c = np.cos(w0)
    s = 2 * np.sqrt(A) * a
    b = np.array([A * ((A + 1) + (A - 1) * c + s), -2 * A * ((A - 1) + (A + 1) * c),
                  A * ((A + 1) + (A - 1) * c - s)])
    d = np.array([(A + 1) - (A - 1) * c + s, 2 * ((A - 1) - (A + 1) * c),
                  (A + 1) - (A - 1) * c - s])
    return signal.lfilter(b / d[0], d / d[0], x, axis=0)


def limita_tp(x, sr, teto_db=-1.0, janela=0.0015, os=4):
    """Limitador de pico VERDADEIRO, com o teto garantido por construcao.

    Superamostra, calcula o ganho necessario ponto a ponto, aplica um
    minimo deslizante na janela e SO ENTAO suaviza. Nessa ordem cada valor
    que a media percorre ja e o minimo da vizinhanca daquele ponto, entao
    o ganho suavizado nunca fica acima do necessario em lugar nenhum — o
    teto sai garantido sem depender de sintonia de attack e release.
    """
    up = signal.resample_poly(x, os, 1, axis=0)
    env = np.abs(up).max(axis=1)
    g = np.minimum(1.0, 10 ** (teto_db / 20) / np.maximum(env, 1e-12))
    L = int(round(janela * sr * os))
    g = minimum_filter1d(g, size=2 * L + 1, mode="nearest")
    k = np.hanning(2 * L + 1)
    k /= k.sum()
    g = np.convolve(np.pad(g, L, mode="edge"), k, mode="same")[L:-L]
    gb = g[::os][: len(x)]
    if len(gb) < len(x):
        gb = np.pad(gb, (0, len(x) - len(gb)), mode="edge")
    return x * gb[:, None], gb


# ------------------------------------------------------------------ cadeia
def trata(x, sr, a):
    """Aplica a cadeia inteira. Devolve (sinal, relatorio)."""
    rel = {}
    e0 = (x**2).sum()
    y = hpf(x, sr, a.hpf)
    rel["hpf_energia_removida_pct"] = 100 * (1 - (y**2).sum() / e0) if e0 else 0.0

    y, g, _ = rider(y, sr, faixa=a.rider, suav=a.rider_suave)
    if len(g) > 1:
        rel["rider_ganho_min_max"] = (float(g.min()), float(g.max()))
        rel["rider_dB_por_s"] = float(np.abs(np.diff(g) / 0.100).max())

    if a.brilho:
        y = brilho(y, sr, a.brilho)

    if a.reverb == "conv":
        y = reverb_conv(y, sr, a.wet, a.rt60, a.predelay / 1000.0)
    elif a.reverb == "freeverb":
        y = reverb_freeverb(y, sr, a.wet)
    elif a.reverb not in ("nenhum", "seco"):
        sys.exit(f"reverb desconhecido: {a.reverb}")

    ganho = a.lufs - integrado(y, sr)
    y = y * 10 ** (ganho / 20)
    rel["ganho_para_alvo_dB"] = float(ganho)
    rel["tp_antes_do_limite"] = truepeak(y, sr)

    y, gl = limita_tp(y, sr, a.tp)
    rel["limite_pct_amostras"] = float(100 * (gl < 0.9999).mean())
    rel["limite_reducao_max_dB"] = float(20 * np.log10(gl.min()))
    return y, rel


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("entrada")
    p.add_argument("saida")
    p.add_argument("--reverb", default="conv", choices=["conv", "freeverb", "nenhum", "seco"])
    p.add_argument("--wet", type=float, default=-15.5, help="nivel do reverb em dB (padrao -15.5)")
    p.add_argument("--rt60", type=float, default=1.3, help="s, so no reverb conv")
    p.add_argument("--predelay", type=float, default=25.0, help="ms, so no reverb conv")
    p.add_argument("--hpf", type=float, default=70.0, help="Hz, 0 desliga")
    p.add_argument("--rider", type=float, default=3.0, help="teto do ganho lento em dB, 0 desliga")
    p.add_argument("--rider-suave", type=float, default=2.0, help="s de suavizacao do ganho")
    p.add_argument("--brilho", type=float, default=0.0, help="dB de high shelf em 8 kHz")
    p.add_argument("--lufs", type=float, default=-14.0)
    p.add_argument("--tp", type=float, default=-1.0, help="teto de pico verdadeiro em dBTP")
    p.add_argument("--amostras", type=int, default=0,
                   help="numero exato de amostras na saida (completa com silencio ou apara)")
    p.add_argument("--recorte", default="", help="INICIO:FIM em segundos, para gerar um trecho de A/B")
    p.add_argument("--bits", type=int, default=24, choices=[16, 24, 32])
    a = p.parse_args()

    x, sr = sf.read(a.entrada, always_2d=True, dtype="float64")
    if sr != SR_ESPERADO:
        sys.exit(f"esperava {SR_ESPERADO} Hz, veio {sr}")

    # Completa ANTES de tratar, nao depois: assim a cauda do reverb decai
    # dentro das amostras que faltam em vez de ser cortada a seco. No
    # improviso_3 a fonte tem 2913408 amostras onde o pedido eram 2913600.
    if a.amostras and not a.recorte and len(x) < a.amostras:
        x = np.pad(x, ((0, a.amostras - len(x)), (0, 0)))

    y, rel = trata(x, sr, a)

    if a.recorte:
        i, f = (float(v) for v in a.recorte.split(":"))
        y = y[int(i * sr): int(f * sr)]
        # Renormaliza o RECORTE. Sem isto cada variante sai com um LUFS
        # ligeiramente diferente (medido: 0,24 dB entre a seca e a de
        # reverb amplo, porque o reverb muda o integrado do arquivo
        # inteiro), e numa comparacao a ouvido o mais alto ganha sozinho.
        y = y * 10 ** ((a.lufs - integrado(y, sr)) / 20)
        y, _ = limita_tp(y, sr, a.tp)

    if a.amostras:
        if len(y) > a.amostras:
            y = y[: a.amostras]
        elif len(y) < a.amostras:
            y = np.pad(y, ((0, a.amostras - len(y)), (0, 0)))

    sf.write(a.saida, y, sr, subtype={16: "PCM_16", 24: "PCM_24", 32: "FLOAT"}[a.bits])

    print(f"    {a.saida}")
    print("      I=%.2f LUFS  LRA=%.2f LU  TP=%.2f dBTP  %d amostras (%.3f s)"
          % (integrado(y, sr), lra(y, sr), truepeak(y, sr), len(y), len(y) / sr))
    for k, v in rel.items():
        print(f"      {k}: {v}")


if __name__ == "__main__":
    main()
