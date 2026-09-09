#!/usr/bin/env python3
"""Mede se a cartela é legível sobre o vídeo real, e não sobre um cinza.

Mesmo método do scripts/valida-legenda.py — renderizar com e sem, usar os
pixels que mudaram como máscara do texto — com uma diferença que a cartela
exige: aqui existem TRÊS fundos possíveis, e confundi-los dá o número errado.

  1. o vídeo cru        — o que existiria sem scrim e sem contorno
  2. o vídeo com scrim  — o que o scrim entrega, antes de a letra ter contorno
  3. o contorno         — o que de fato faz fronteira com o miolo do traço

A coluna que decide se a peça está boa é a 2: é ela que diz se o scrim está
forte o bastante para a letra se sustentar sem depender do contorno. A 3 é a
rede, e a 1 é o tamanho do problema que as outras duas resolvem.

Duas correções que o docs/04 registra como necessárias e que estão aplicadas:

  - a máscara é EROD1DA antes de medir. A borda de antialiasing é meio-tom
    entre texto e fundo, então por definição tem contraste baixo; contá-la
    acusa ilegibilidade onde não há;
  - o contorno NÃO conta como texto. Ele é escuro de propósito. Contando-o,
    pôr contorno "piora" o número exatamente ao tornar a peça mais legível.

Uso:
    python scripts/valida-cartela.py out/improviso_3/improviso_3_cover.mp4 \
        --cartela work/improviso_3_cover.abertura.png:4.0 \
        --cartela work/improviso_3_cover.creditos.png:56.0
"""
import argparse
import pathlib
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image
from scipy import ndimage

RAIZ = pathlib.Path(__file__).resolve().parent.parent
LIMIAR_WCAG = 4.5
MIN_PIXELS = 200


def tokens() -> dict:
    import tomllib
    with (RAIZ / "marca" / "tokens.toml").open("rb") as f:
        return tomllib.load(f)


def frame(video: str, t: float, destino: str, overlay: str | None = None):
    """Um frame em `t`, opcionalmente já com a cartela composta.

    -copyts é obrigatório. Sem ele o -ss rebaseia os timestamps para zero, e
    qualquer filtro com noção de tempo passa a agir na hora errada — o frame
    sai limpo e a medição inteira vira fundo contra fundo, sem acusar nada.
    """
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-copyts",
           "-ss", f"{t:.3f}", "-i", video]
    if overlay:
        cmd += ["-i", overlay,
                "-filter_complex", "[0:v][1:v]overlay=0:0:format=auto[v]",
                "-map", "[v]"]
    cmd += ["-frames:v", "1", destino]
    subprocess.run(cmd, check=True)


def luminancia(rgb: np.ndarray) -> np.ndarray:
    c = rgb / 255.0
    c = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * c[..., 0] + 0.7152 * c[..., 1] + 0.0722 * c[..., 2]


def contraste(l1, l2):
    a, b = np.maximum(l1, l2), np.minimum(l1, l2)
    return (a + 0.05) / (b + 0.05)


def hex_rgb(h: str) -> np.ndarray:
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], dtype=float)


def mede(video, png, t, tmp, cor_contorno):
    sem_txt = png.replace(".png", ".sem-texto.png")
    if not pathlib.Path(sem_txt).exists():
        sys.exit(f"falta a camada de referência: {sem_txt}\n"
                 "gere com  python scripts/cartelas.py ... --sem-texto")

    a, b, c = f"{tmp}/cru.png", f"{tmp}/full.png", f"{tmp}/scrim.png"
    frame(video, t, a)
    frame(video, t, b, png)
    frame(video, t, c, sem_txt)
    cru = np.array(Image.open(a).convert("RGB")).astype(np.float64)
    full = np.array(Image.open(b).convert("RGB")).astype(np.float64)
    scr = np.array(Image.open(c).convert("RGB")).astype(np.float64)
    if not (cru.shape == full.shape == scr.shape):
        sys.exit("os frames saíram com tamanhos diferentes")

    # o miolo do texto: mudou muito em relação à camada de scrim (não ao vídeo
    # cru — assim o scrim não entra na máscara) e ficou claro.
    dif = np.abs(full - scr).max(axis=2)
    bruta = (dif > 60) & (full.min(axis=2) > 200)
    # erosão: tira a borda de antialiasing, que é meio-tom por construção
    miolo = ndimage.binary_erosion(bruta, np.ones((3, 3)), iterations=1)
    if miolo.sum() < MIN_PIXELS:
        return None

    l_txt = luminancia(full[miolo])
    return {
        "px": int(miolo.sum()),
        "bruta": int(bruta.sum()),
        "video": contraste(l_txt, luminancia(cru[miolo])),
        "scrim": contraste(l_txt, luminancia(scr[miolo])),
        "contorno": contraste(l_txt, np.full_like(l_txt,
                                                  luminancia(cor_contorno))),
    }


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("--cartela", action="append", required=True,
                    metavar="PNG:SEGUNDOS",
                    help="pode repetir; mede o PNG sobre o frame daquele instante")
    args = ap.parse_args()

    t = tokens()
    cor_contorno = hex_rgb(t["paleta"]["fundo"])
    print(f"{args.video}\ncontorno = {t['paleta']['fundo']} "
          f"(luminância {luminancia(cor_contorno):.4f})\n")
    print(f"{'cartela':>34}{'t':>8}{'px':>8}"
          f"{'vs vídeo':>11}{'vs scrim':>11}{'vs contorno':>13}{'ruins':>8}")

    pior_scrim, pior_contorno, falhou = [], [], False
    with tempfile.TemporaryDirectory() as tmp:
        for spec in args.cartela:
            png, _, seg = spec.rpartition(":")
            r = mede(args.video, png, float(seg), tmp, cor_contorno)
            nome = pathlib.Path(png).name
            if r is None:
                print(f"{nome:>34}{float(seg):>8.2f}   (sem texto visível)")
                continue
            ruins = int((r["scrim"] < LIMIAR_WCAG).sum())
            pior_scrim.append(float(r["scrim"].min()))
            pior_contorno.append(float(r["contorno"].min()))
            print(f"{nome:>34}{float(seg):>8.2f}{r['px']:>8}"
                  f"{r['video'].min():>10.1f}:1{r['scrim'].min():>10.1f}:1"
                  f"{r['contorno'].min():>12.1f}:1"
                  f"{ruins / r['px'] * 100:>7.1f}%")
            if ruins:
                falhou = True

    if not pior_scrim:
        sys.exit("nenhuma cartela rendeu máscara — confira os caminhos e os tempos")

    print(f"\npior contraste contra o scrim:    {min(pior_scrim):.1f}:1")
    print(f"pior contraste contra o contorno: {min(pior_contorno):.1f}:1")
    if not falhou and min(pior_scrim) >= LIMIAR_WCAG:
        print(f"\nOK: o scrim sozinho já sustenta {LIMIAR_WCAG}:1 em todo pixel "
              f"de miolo — o contorno é folga, não muleta.")
    else:
        print(f"\nATENÇÃO: há pixel de miolo abaixo de {LIMIAR_WCAG}:1 contra o "
              f"scrim.\nO caminho é ESCURECER o fundo (cartela.scrim_forca em "
              f"marca/tokens.toml),\nnão clarear a letra: com o fundo em luma "
              f"122 nem branco puro chega a 4,5:1.")


if __name__ == "__main__":
    main()
