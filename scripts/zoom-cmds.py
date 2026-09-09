#!/usr/bin/env python3
"""Gera o arquivo de comandos que anima o zoom-out do vertical.sh.

Por que sendcmd e não um filtro de zoom:

  crop  neste ffmpeg (6.1.1) reavalia só `x` e `y` por frame — `w` e `h`
        são resolvidos uma vez, na configuração. Dá para deslocar a janela,
        não para abri-la.
  zoompan só sabe aproximar: `z` tem piso em 1, e o que se quer aqui é o
        contrário — afastar até o quadro inteiro caber na tela.

O que sobra é `scale`, cujos `w`/`h` são ajustáveis em runtime (o flag T no
`ffmpeg -h filter=scale`). Um comando por frame do master, e o `overlay`
seguinte recentra sozinho, porque a expressão dele lê `overlay_w`.

A curva é smoothstep, não linear: um zoom que começa e termina na velocidade
máxima parece um corte mal feito. Com 3p²-2p³ o movimento sai do repouso e
chega ao repouso.
"""
import argparse


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--inicio", type=float, required=True,
                    help="instante em que o zoom-out começa, em segundos")
    ap.add_argument("--duracao", type=float, required=True)
    ap.add_argument("--fps", type=float, required=True,
                    help="taxa do MASTER — é por frame dele que o comando dispara")
    ap.add_argument("--de", type=int, required=True, help="largura no fechado")
    ap.add_argument("--para", type=int, required=True, help="largura no aberto")
    ap.add_argument("--proporcao", type=float, required=True,
                    help="altura/largura do master, para a altura acompanhar")
    ap.add_argument("--saida", required=True)
    a = ap.parse_args()

    n = max(1, int(round(a.duracao * a.fps)))
    linhas = []
    for i in range(n + 1):
        t = a.inicio + i / a.fps
        p = i / n
        sm = p * p * (3 - 2 * p)
        w = int(round((a.de + sm * (a.para - a.de)) / 2) * 2)
        h = int(round(w * a.proporcao / 2) * 2)
        linhas.append(f"{t:.4f} scale@z w {w}, scale@z h {h};")
    with open(a.saida, "w", encoding="utf-8") as f:
        f.write("\n".join(linhas) + "\n")
    print(f"    zoom-out: {n + 1} comandos, {a.inicio:.2f}s -> "
          f"{a.inicio + a.duracao:.2f}s, {a.de} -> {a.para} px de largura")


if __name__ == "__main__":
    main()
