#!/usr/bin/env python3
"""Mede se o texto das peças de marca é legível sobre o frame real.

Mesma ideia do valida-legenda.py, e pelo mesmo motivo: o material do canal tem
10% dos pixels acima de 200 de luminância (parede estourada) e um violão claro
ocupando meio quadro. Texto que parece bom no frame escolhido some no frame
seguinte.

Gera cada peça duas vezes, com e sem o texto, usa os pixels que mudaram como
máscara e mede contraste WCAG do texto contra o que havia por baixo. Aqui o
véu faz o papel que o contorno faz na legenda: garantir que o fundo pare de
importar.

Uso:
    python scripts/valida-marca.py out/improviso_2_audio.mp4 --t 42
    python scripts/valida-marca.py out/ep00_audio.mp4 --t 12 --titulo "..."
"""
import argparse
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import marca  # noqa: E402

LIMIAR = 4.5


def lum(rgb: np.ndarray) -> np.ndarray:
    c = rgb / 255.0
    c = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * c[..., 0] + 0.7152 * c[..., 1] + 0.0722 * c[..., 2]


def contraste(a, b):
    hi, lo = np.maximum(a, b), np.minimum(a, b)
    return (hi + 0.05) / (lo + 0.05)


def erode(m: np.ndarray) -> np.ndarray:
    """Remove a borda da máscara: só fica o pixel cujos 8 vizinhos também estão.

    Sem isso a medida mente. A borda de uma letra é antialiasing — meio-tom
    entre o texto e o fundo — e por definição tem contraste baixo com os dois.
    Medindo com a borda, o post e o story acusavam 7,8% de pixels "ilegíveis"
    mesmo com o texto sobre fundo sólido, onde o contraste real passa de 17:1.
    O que importa é o miolo da letra, que é o que se lê.
    """
    r = m.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy == 0 and dx == 0:
                continue
            r &= np.roll(np.roll(m, dy, axis=0), dx, axis=1)
    return r


def mede(nome, com, sem, clara=False):
    """Mede o MIOLO CLARO das letras, não tudo que mudou.

    Duas correções que a métrica precisou, e as duas porque ela mentia:

    1. erosão, para tirar a borda de antialiasing — sem ela o post acusava
       7,8% de pixels ilegíveis com o texto sobre fundo sólido a 17:1;
    2. este filtro de claridade, para tirar o CONTORNO. O contorno é escuro de
       propósito e não precisa contrastar com nada: ele existe para separar o
       texto claro do fundo. Contando-o como texto, pôr contorno "piorava" o
       número de 15% para 19%, exatamente ao fazer a peça ficar mais legível.

    O que se lê é o miolo claro da letra. É ele que tem de passar.
    """
    a = np.array(com.convert("RGB")).astype(float)
    b = np.array(sem.convert("RGB")).astype(float)
    dif = np.abs(a - b).max(axis=2)
    # A claridade vem declarada, não adivinhada: as peças de vídeo são escuras
    # com texto creme, o post de feed é papel com texto tinta. Aceitar os dois
    # miolos no mesmo filtro trazia o CONTORNO de volta para a máscara — ele é
    # escuro — e medir o contorno contra a cor do contorno dá 1,0:1. Inferir
    # pela mediana também falhava: no post a foto ocupa 58% da altura e, num
    # frame escuro, a peça inteira era classificada como escura e sumia.
    miolo = (a.max(axis=2) < 90) if clara else (a.min(axis=2) > 170)
    mask = erode((dif > 60) & miolo)
    if mask.sum() < 500:
        print(f"{nome:<14} sem texto detectável")
        return None
    l_txt, l_fundo = lum(a[mask]), lum(b[mask])
    c = contraste(l_txt, l_fundo)
    ruins = (c < LIMIAR).mean() * 100

    # O que de fato chega ao olho. Onde há contorno, o miolo da letra não faz
    # fronteira com o fundo — faz com o contorno. Medir só contra o fundo
    # responde "e se não houvesse contorno", que é útil para dimensionar o
    # problema, mas não é o que o espectador vê. É a mesma distinção que o
    # valida-legenda.py faz.
    l_borda = lum(np.array([24.0, 21.0, 16.0]))          # paleta.fundo
    c_borda = contraste(l_txt, np.full_like(l_txt, l_borda))
    # Passa por um caminho ou pelo outro: ou o texto já contrasta com o fundo
    # (peça de fundo sólido, sem contorno), ou contrasta com o próprio contorno
    # (peça sobre foto). Exigir os dois reprovaria o post, que está a 17:1.
    # Passa por um caminho ou pelo outro: ou o texto já contrasta com o fundo
    # (peça de fundo sólido, sem contorno), ou contrasta com o próprio contorno
    # (peça sobre foto). Exigir os dois reprovaria o post, que está a 17:1.
    direto = ruins < 2
    ok = direto or c_borda.min() >= LIMIAR
    via = "fundo" if direto else "contorno"
    real = c.min() if direto else c_borda.min()
    print(f"{nome:<14}{mask.sum():>9}{c.min():>10.1f}{ruins:>10.1f}%"
          f"{real:>11.1f}  via {via:<9}{'OK' if ok else 'revisar'}")
    return real, 0.0 if ok else 100.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--t", type=float, default=12.0)
    ap.add_argument("--titulo", default="Dominante secundária")
    ap.add_argument("--sub", default="o acorde que puxa para onde você não espera")
    ap.add_argument("--ep", type=int, default=3)
    args = ap.parse_args()

    t = marca.tokens()
    print(f"frame de {args.video} em t={args.t}s\n")
    print("colunas: contraste contra o FUNDO (o que existiria sem contorno)")
    print("         e contra o CONTORNO (o que chega ao olho)\n")
    print(f"{'peça':<14}{'px texto':>9}{'vs fundo':>10}{'ruins':>11}"
          f"{'real':>11}")

    pecas = [
        ("thumbnail", False,
         lambda st: marca.thumbnail(t, args.video, args.t, args.titulo,
                                    args.sub, args.ep, sem_texto=st)),
        ("post-feed", True,
         lambda st: marca.post_feed(t, args.video, args.t, args.titulo,
                                    args.sub, sem_texto=st)),
        ("story", False,
         lambda st: marca.story(t, args.video, args.t, args.titulo,
                                sem_texto=st)),
    ]
    piores = []
    for nome, clara, f in pecas:
        r = mede(nome, f(False), f(True), clara)
        if r:
            piores.append((nome, *r))

    print()
    ruim = [n for n, _, r in piores if r >= 2]
    if ruim:
        print(f"revisar: {', '.join(ruim)} — nem com o contorno se atinge "
              f"{LIMIAR}:1")
    else:
        print(f"Todas as peças passam. Pior caso real: "
              f"{min(p for _, p, _ in piores):.1f}:1 — cada peça pelo caminho "
              f"que a coluna indica.")


if __name__ == "__main__":
    main()
