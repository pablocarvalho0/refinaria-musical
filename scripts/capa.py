#!/usr/bin/env python3
"""Procura os melhores frames de um vídeo para servir de capa.

A escolha da capa tem duas partes, e só uma delas é trabalho de máquina:

  - determinístico: nitidez, exposição e variedade. É o que este script faz.
  - julgamento: expressão do rosto, o instante que conta a história. É humano.

Então ele não escolhe: ele reduz 1523 frames a uma dúzia de candidatos
defensáveis e monta uma folha de contato para alguém decidir.

Nitidez é a variância do laplaciano do luma — o operador realça bordas, e
imagem borrada tem poucas. Exposição é a fração de pixels estourados ou
esmagados, que penaliza frame contra janela ou dentro de sombra. E há uma
separação mínima no tempo, senão os dez melhores são o mesmo instante dez
vezes, porque frames vizinhos têm nitidez quase igual.

Uso:
  python scripts/capa.py video.mp4 --saida out/<ep>/capas [--n 12] [--largura 540]
  python scripts/capa.py video.mp4 --trechos 0-2.7,15.4-22.5,46.7-50.7
"""
import argparse, subprocess, sys
from pathlib import Path
import numpy as np

import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
from projeto import pasta_projeto

# Laplaciano 3x3 (8-vizinhos): realça borda em qualquer direção.
LAP = np.array([[1, 1, 1], [1, -8, 1], [1, 1, 1]], dtype=np.float32)


def sonda(v, campo):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                        "-show_entries", f"stream={campo}", "-of", "csv=p=0", v],
                       capture_output=True, text=True)
    return r.stdout.strip()


def laplaciano(img):
    """Convolução 3x3 sem scipy: soma de deslocamentos da própria matriz."""
    out = np.zeros_like(img)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            k = LAP[dy + 1, dx + 1]
            if k:
                out[1:-1, 1:-1] += k * img[1 + dy:img.shape[0] - 1 + dy,
                                           1 + dx:img.shape[1] - 1 + dx]
    return out[1:-1, 1:-1]


def analisa(video, larg, fps_saida):
    alt_real = int(sonda(video, "height")); larg_real = int(sonda(video, "width"))
    alt = int(round(larg * alt_real / larg_real / 2)) * 2
    p = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", video,
         "-vf", f"scale={larg}:{alt}", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        stdout=subprocess.PIPE)
    n_bytes = larg * alt
    linhas, i = [], 0
    while True:
        buf = p.stdout.read(n_bytes)
        if len(buf) < n_bytes:
            break
        g = np.frombuffer(buf, dtype=np.uint8).reshape(alt, larg).astype(np.float32)
        lap = laplaciano(g)
        estourado = float((g > 250).mean())
        esmagado = float((g < 6).mean())
        linhas.append((i, float(lap.var()), estourado, esmagado, float(g.mean())))
        i += 1
    p.stdout.close(); p.wait()
    return linhas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    # o default acompanha o vídeo: as capas do episódio ficam com ele
    ap.add_argument("--saida", default=None,
                    help="padrão: out/<projeto>/capas")
    ap.add_argument("--n", type=int, default=12, help="quantos candidatos")
    ap.add_argument("--largura", type=int, default=540, help="resolução da análise")
    ap.add_argument("--separacao", type=float, default=1.5,
                    help="segundos mínimos entre candidatos")
    ap.add_argument("--trechos", default="", help="ex: 0-2.7,15.4-22.5")
    a = ap.parse_args()

    fps = eval(sonda(a.video, "r_frame_rate"))
    dados = analisa(a.video, a.largura, fps)
    if not dados:
        sys.exit("não consegui decodificar frame nenhum")
    arr = np.array(dados)
    idx, nit, est, esm, med = arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3], arr[:, 4]
    t = idx / fps

    janelas = []
    for tr in filter(None, a.trechos.split(",")):
        i, f = tr.split("-"); janelas.append((float(i), float(f)))
    dentro = np.ones(len(t), bool)
    if janelas:
        dentro = np.zeros(len(t), bool)
        for i, f in janelas:
            dentro |= (t >= i) & (t <= f)

    # nota: nitidez normalizada, penalizada por estouro/esmagamento e por
    # luma muito fora do meio (quadro chapado de claro ou de escuro).
    n_nit = nit / nit.max()
    pena = 1.0 - np.clip(est * 4 + esm * 2, 0, 0.9)
    equil = 1.0 - np.abs(med - 118) / 118 * 0.5
    nota = n_nit * pena * equil
    nota[~dentro] = -1

    print(f"{len(dados)} frames a {fps:g} fps ({t[-1]:.2f} s)")
    print(f"nitidez  mediana {np.median(nit):8.1f}   máx {nit.max():8.1f}")

    escolhidos = []
    for k in np.argsort(nota)[::-1]:
        if nota[k] < 0:
            break
        if all(abs(t[k] - t[j]) >= a.separacao for j in escolhidos):
            escolhidos.append(k)
        if len(escolhidos) == a.n:
            break
    escolhidos.sort(key=lambda k: t[k])

    saida = Path(a.saida) if a.saida else pasta_projeto(a.video) / "capas"
    saida.mkdir(parents=True, exist_ok=True)
    print(f"\n{'#':>3} {'tempo':>7} {'frame':>6} {'nitidez':>9} {'estourado':>10} {'nota':>6}")
    arquivos = []
    for r, k in enumerate(escolhidos, 1):
        nome = saida / f"capa_{r:02d}_{t[k]:06.2f}s.png"
        subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t[k]:.4f}", "-i", a.video,
                        "-frames:v", "1", "-y", str(nome)], check=True)
        arquivos.append(nome)
        print(f"{r:3d} {t[k]:7.2f} {int(idx[k]):6d} {nit[k]:9.1f} "
              f"{est[k]*100:9.1f}% {nota[k]:6.3f}")

    folha = saida / "folha.png"
    cols = 6
    subprocess.run(["ffmpeg", "-v", "error", "-pattern_type", "glob",
                    "-i", str(saida / "capa_*.png"),
                    "-filter_complex",
                    f"scale=260:-1,tile={cols}x{(len(arquivos)+cols-1)//cols}"
                    ":margin=8:padding=8:color=0x141414",
                    "-frames:v", "1", "-y", str(folha)], check=True)
    print(f"\nfolha de contato: {folha}")


if __name__ == "__main__":
    main()
