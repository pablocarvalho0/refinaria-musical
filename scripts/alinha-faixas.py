#!/usr/bin/env python3
"""Mede o deslocamento entre duas gravações da mesma música.

Uso:  python scripts/alinha-faixas.py REFERENCIA.wav OUTRA.wav [--ancora T0 T1]

Ambos precisam ser WAV mono 16 bits. Imprime o offset em milissegundos que a
segunda faixa precisa ser ATRASADA para casar com a primeira, e um diagnóstico
de deriva ao longo da faixa.

POR QUE NÃO É CORRELAÇÃO GLOBAL. Duas performances tocadas sem metrônomo
flutuam ~2% de andamento cada, de forma independente. Correlacionar a faixa
inteira encontra um pico em quase qualquer lugar, porque música repetitiva
casa consigo mesma a cada compasso — medido em 30/08/2026 no oficina-g3: o
lag por janela saltava entre -6,4s e -17,9s com "confiança" alta em todas.

O que funciona é ancorar numa passagem curta de ataques fortes que os dois
músicos tocam juntos, e depois VERIFICAR se o offset encontrado se sustenta.
"""
import argparse, sys, wave
import numpy as np

SR = 48000
RES_MS = 1.0                      # resolução do envelope


def le_wav(p):
    with wave.open(p, 'rb') as w:
        if w.getsampwidth() != 2 or w.getnchannels() != 1:
            sys.exit(f"{p}: precisa ser WAV mono 16 bits")
        if w.getframerate() != SR:
            sys.exit(f"{p}: precisa ser {SR} Hz, veio {w.getframerate()}")
        return np.frombuffer(w.readframes(w.getnframes()), '<i2').astype(np.float64) / 32768.0


def envelope(x):
    """Derivada positiva do envelope de pico: realça ataques, ignora timbre.

    Timbre é o que separa violão de bateria; o ataque é o que eles têm em
    comum. Correlacionar forma de onda direta entre instrumentos diferentes
    não funciona — correlacionar ataque funciona.
    """
    W = int(RES_MS * SR / 1000)
    e = np.array([np.abs(x[i*W:(i+1)*W]).max() for i in range(len(x)//W)])
    e = np.convolve(e, np.ones(5)/5, mode='same')
    return np.maximum(np.diff(e, prepend=e[0]), 0)


def corr(a, b):
    n = 1 << int(np.ceil(np.log2(len(a) + len(b))))
    c = np.fft.irfft(np.fft.rfft(a, n) * np.conj(np.fft.rfft(b, n)), n)
    c = np.concatenate([c[-(len(b)-1):], c[:len(a)]])
    return c, np.arange(-(len(b)-1), len(a))


def primeiro_som(e, limiar_frac=0.15):
    """Onde a faixa realmente começa, em segundos."""
    lim = limiar_frac * e.max()
    i = int(np.argmax(e > lim))
    return i * RES_MS / 1000.0


def offset_na_ancora(ea, eb, ta0, ta1, tb0, tb1):
    """Offset (ms) que alinha o trecho [ta0,ta1] de A com [tb0,tb1] de B."""
    A = ea[int(ta0*1000):int(ta1*1000)]; A = A - A.mean()
    B = eb[int(tb0*1000):int(tb1*1000)]; B = B - B.mean()
    c, lags = corr(A, B)
    off = lags + (ta0 - tb0) * 1000
    k = int(np.argmax(c))
    if 0 < k < len(c) - 1:                      # refino sub-milissegundo
        y0, y1, y2 = c[k-1], c[k], c[k+1]
        den = y0 - 2*y1 + y2
        k = k + (0.5*(y0 - y2)/den if den else 0)
    ki = int(round(k))
    picos = sorted(range(len(c)), key=lambda i: -c[i])
    seg = next((c[i] for i in picos if abs(i - ki) > 60), 0.0)
    return float(np.interp(k, np.arange(len(off)), off)), c[ki], seg


def deriva(ea, eb, off_s, t0, t1, win=3.0, passo=2.0, raio_ms=180):
    """Como o offset ideal varia ao longo da faixa. Devolve lista (t, desvio_ms)."""
    out = []
    t = t0
    while t + win <= t1:
        td0, td1 = t - off_s - raio_ms/1000, t - off_s + win + raio_ms/1000
        if td0 >= 0 and td1*1000 <= len(eb):
            A = ea[int(t*1000):int((t+win)*1000)]; A = A - A.mean()
            B = eb[int(td0*1000):int(td1*1000)]; B = B - B.mean()
            c, lags = corr(A, B)
            off = lags + (t - td0) * 1000
            m = np.abs(off - off_s*1000) <= raio_ms
            if m.any():
                out.append((t, float(off[m][np.argmax(c[m])] - off_s*1000)))
        t += passo
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('ref'); ap.add_argument('outra')
    ap.add_argument('--ancora', nargs=2, type=float, metavar=('T0', 'T1'),
                    help='trecho da REFERENCIA usado como âncora (s). '
                         'Padrão: 1,3s a partir do primeiro som.')
    ap.add_argument('--busca', type=float, default=3.0,
                    help='raio de busca em torno do alinhamento por início (s)')
    a = ap.parse_args()

    xa, xb = le_wav(a.ref), le_wav(a.outra)
    ea, eb = envelope(xa), envelope(xb)
    ia, ib = primeiro_som(ea), primeiro_som(eb)
    print(f"{a.ref}:   {len(xa)/SR:7.3f}s   primeiro som em {ia:6.3f}s")
    print(f"{a.outra}: {len(xb)/SR:7.3f}s   primeiro som em {ib:6.3f}s")

    ta0, ta1 = a.ancora if a.ancora else (ia - 0.05, ia + 1.25)
    tb0 = max(0.0, ta0 - (ia - ib) - a.busca)
    tb1 = min(len(eb)/1000.0, ta1 - (ia - ib) + a.busca)
    print(f"\nâncora: {ta0:.3f}-{ta1:.3f}s da referência, procurada em "
          f"{tb0:.3f}-{tb1:.3f}s da outra")

    off_ms, pico, seg = offset_na_ancora(ea, eb, ta0, ta1, tb0, tb1)
    margem = 100 * (1 - seg/pico) if pico else 0
    print(f"\n  OFFSET = {off_ms:+.1f} ms  ({int(round(off_ms*SR/1000))} amostras a {SR} Hz)")
    print(f"  {'atrase' if off_ms>0 else 'adiante'} a segunda faixa em {abs(off_ms):.0f} ms")
    print(f"  2º candidato a {100-margem:.0f}% do melhor "
          f"({'separado, confiável' if margem>25 else 'PERTO DEMAIS — confira ouvindo'})")

    d = deriva(ea, eb, off_ms/1000.0, ta0, min(len(xa)/SR, len(xb)/SR + off_ms/1000) - 3.2)
    if d:
        v = np.array([x[1] for x in d])
        print(f"\n=== deriva ao longo da faixa ({len(d)} janelas de 3s) ===")
        for t, dd in d:
            barra = '#' * min(40, int(abs(dd)/5))
            print(f"  t={t:5.1f}s  {dd:+7.0f} ms  {barra}")
        dentro = np.abs(v) < 40
        print(f"\n  |desvio| médio {np.abs(v).mean():.0f} ms   máximo {np.abs(v).max():.0f} ms")
        print(f"  janelas dentro de ±40 ms: {dentro.sum()}/{len(v)}")
        tend = np.polyfit(np.arange(len(v)), v, 1)[0] * len(v)
        print(f"  tendência acumulada: {tend:+.0f} ms do começo ao fim")
        if abs(tend) > 100:
            print("  -> há DERIVA de andamento: um offset fixo não segura a faixa toda.")
        else:
            print("  -> sem deriva acumulada: as duas flutuam em torno do mesmo")
            print("     andamento médio. Offset fixo serve para a faixa inteira.")


if __name__ == '__main__':
    main()
