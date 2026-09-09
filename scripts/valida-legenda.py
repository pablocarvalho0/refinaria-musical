#!/usr/bin/env python3
"""Mede se a legenda é legível sobre o vídeo real, e não sobre um fundo cinza.

Legenda falha por causa do fundo, sempre. No ep00 o fundo é parede branca
estourada em alguns trechos e sombra em outros, e a mesma legenda tem de
sobreviver aos dois. Julgar isso a olho, num frame escolhido a dedo, é como
escolher a janela da medição depois de ver o resultado.

Como mede: para cada cue, renderiza o frame com e sem a legenda queimada. Os
pixels que mudaram são a legenda. Sobre essa máscara mede duas razões de
contraste (WCAG 2.x, que é a única definição com limiar acordado):

  texto contra o FUNDO      o contraste que existiria sem contorno
  texto contra o CONTORNO   o contraste que de fato chega ao olho

A segunda é praticamente constante — branco contra quase-preto — e é esse o
ponto: **o contorno é o que torna a legenda independente do fundo**. A
primeira é a que mostra o tamanho do problema que o contorno resolve, e é a
que denuncia um contorno fino demais para o tamanho da fonte.

Uso:
    python scripts/valida-legenda.py out/ep00/ep00_audio.mp4 out/ep00/ep00.16x9.ass
    python scripts/valida-legenda.py out/ep00/ep00_audio.mp4 out/ep00/ep00.9x16.ass \
        --vf "crop=608:1080:656:0,scale=1080:1920"
"""
import argparse
import pathlib
import re
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image

LIMIAR_WCAG = 4.5      # AA para texto normal; texto grande passaria com 3.0
MIN_PIXELS = 200       # abaixo disso o cue não rendeu máscara utilizável


def tempos_dos_cues(ass: pathlib.Path) -> list[tuple[float, float]]:
    out = []
    for l in ass.read_text(encoding="utf-8").splitlines():
        if not l.startswith("Dialogue"):
            continue
        c = l.split(",")
        out.append((hms(c[1]), hms(c[2])))
    return out


def hms(t: str) -> float:
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def frame(video: pathlib.Path, t: float, vf: str, destino: str):
    """Um frame em `t`. -copyts é obrigatório: sem ele o -ss rebaseia os
    timestamps para zero e o filtro ass procura a legenda na hora errada —
    o frame sai limpo e a medição inteira vira contraste de fundo com fundo."""
    subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-y", "-copyts", "-ss", f"{t:.3f}",
         "-i", str(video)] + (["-vf", vf] if vf else []) +
        ["-frames:v", "1", destino], check=True)


def luminancia(rgb: np.ndarray) -> np.ndarray:
    """Luminância relativa da WCAG, canal linearizado."""
    c = rgb / 255.0
    c = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * c[..., 0] + 0.7152 * c[..., 1] + 0.0722 * c[..., 2]


def contraste(l1: np.ndarray, l2: np.ndarray) -> np.ndarray:
    a, b = np.maximum(l1, l2), np.minimum(l1, l2)
    return (a + 0.05) / (b + 0.05)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("ass")
    ap.add_argument("--vf", default="", help="filtros antes do ass (ex: crop do vertical)")
    ap.add_argument("--max-cues", type=int, default=12)
    args = ap.parse_args()

    video, ass = pathlib.Path(args.video), pathlib.Path(args.ass)
    for p in (video, ass):
        if not p.exists():
            sys.exit(f"não encontrado: {p}")

    cues = tempos_dos_cues(ass)
    if not cues:
        sys.exit(f"{ass} não tem nenhum Dialogue")
    passo = max(1, len(cues) // args.max_cues)
    cues = cues[::passo][:args.max_cues]

    base_vf = args.vf
    com_vf = (f"{args.vf}," if args.vf else "") + f"ass={ass}"

    print(f"{video.name} + {ass.name}   {len(cues)} cues amostrados\n")
    print(f"{'t':>8}{'px':>8}{'fundo: mín':>13}{'mediana':>10}"
          f"{'contorno':>11}{'abaixo de 4.5':>15}")

    piores_fundo, piores_contorno, total_ruins, total_px = [], [], 0, 0
    with tempfile.TemporaryDirectory() as d:
        for ini, fim in cues:
            t = (ini + fim) / 2
            a, b = f"{d}/sem.png", f"{d}/com.png"
            frame(video, t, base_vf, a)
            frame(video, t, com_vf, b)
            sem = np.array(Image.open(a).convert("RGB")).astype(np.float64)
            com = np.array(Image.open(b).convert("RGB")).astype(np.float64)
            if sem.shape != com.shape:
                sys.exit("os dois frames saíram com tamanhos diferentes")

            dif = np.abs(com - sem).max(axis=2)
            # o miolo do texto: pixels que ficaram claros e mudaram muito
            texto = (dif > 60) & (com.min(axis=2) > 200)
            if texto.sum() < MIN_PIXELS:
                print(f"{t:>8.2f}{texto.sum():>8}   (sem legenda visível neste frame)")
                continue

            l_texto = luminancia(com[texto])
            l_fundo = luminancia(sem[texto])          # o que havia por baixo
            c_fundo = contraste(l_texto, l_fundo)
            # o contorno: a cor de contorno dos tokens, quase preto
            l_contorno = luminancia(np.array([16.0, 16.0, 16.0]))
            c_contorno = contraste(l_texto, np.full_like(l_texto, l_contorno))

            ruins = int((c_fundo < LIMIAR_WCAG).sum())
            total_ruins += ruins
            total_px += int(texto.sum())
            piores_fundo.append(float(c_fundo.min()))
            piores_contorno.append(float(c_contorno.min()))
            print(f"{t:>8.2f}{texto.sum():>8}{c_fundo.min():>13.1f}"
                  f"{np.median(c_fundo):>10.1f}{c_contorno.min():>11.1f}"
                  f"{ruins / texto.sum() * 100:>14.1f}%")

    if not piores_fundo:
        sys.exit("\nnenhum cue rendeu máscara — confira o --vf e o .ass")

    print(f"\nsem o contorno, o pior contraste contra o fundo seria "
          f"{min(piores_fundo):.1f}:1")
    print(f"e {total_ruins / total_px * 100:.1f}% dos pixels do texto ficariam "
          f"abaixo do limiar AA de {LIMIAR_WCAG}:1")
    print(f"com o contorno, o pior caso é {min(piores_contorno):.1f}:1")
    if min(piores_contorno) >= LIMIAR_WCAG:
        print(f"\nOK: o contorno sustenta a legibilidade sozinho — o fundo "
              f"deixa de importar.")
    else:
        print(f"\nATENÇÃO: nem com o contorno se atinge {LIMIAR_WCAG}:1. "
              f"Reveja cor_contorno em marca/tokens.toml.")


if __name__ == "__main__":
    main()
