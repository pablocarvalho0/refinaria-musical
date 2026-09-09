#!/usr/bin/env python3
"""Monta o filtergraph de uma câmera virtual sobre um master parado.

O problema: o entregável vertical é 1080x1920 e o master, girado, é 2160x3840.
Sobra exatamente um fator 2 — então dá para *enquadrar* dentro do master
(aproximar, deslocar, voltar) sem nunca ampliar nada. Zoom 2,00 é recorte 1:1.
Acima disso é ampliação, e o script recusa.

Por que `scale` e não os candidatos óbvios — a mesma lista do zoom-cmds.py,
com uma correção medida em 05/09/2026:

  crop     reavalia só `x` e `y` por frame; `w`/`h` são resolvidos na
           configuração. Desloca a janela, não a abre. (Ainda vale.)
  zoompan  só sabe aproximar (`z` tem piso em 1) e trabalha em passo inteiro.
  scale    **tem `eval=frame` neste ffmpeg 6.1.1.** O zoom-cmds.py nasceu
           supondo que só o `sendcmd` alcançava `w`/`h`; alcança a expressão
           direta também, e aí a animação inteira cabe em duas expressões de
           `t`, sem arquivo de comandos e sem risco de comando perdido.

**`in_w` no crop NÃO acompanha um scale com `eval=frame`** — medido em
05/09/2026, e é a armadilha central deste script. O `vertical.sh` recentra
lendo `overlay_w`, e a tentação era repetir o padrão aqui. Mas `in_w`/`in_h`
são resolvidos na configuração do link e ficam parados: com o primeiro
enquadramento em zoom 1,00, o crop leu 1080 pelos 60 s inteiros, e todo
enquadramento ampliado saiu deslocado para o canto superior esquerdo. Nenhum
aviso, código de saída 0 — o vídeo se move, só se move para o lugar errado.
O preview em frame estático não pega: lá o scale é fixo e `in_w` está certo.

Então o crop repete a expressão de largura em vez de perguntá-la. Continua
preso à escala e não ao relógio — é a mesma função de `t`, avaliada no mesmo
frame —, só que agora por construção, não por leitura.

Por isso também a altura é explícita em vez de `h=-2`: o clamp precisa do
número exato, e pedir ao crop um `y` dois pixels além do que o swscaler
escolheu mata o render. O preço é ≤0,19% de anisotropia (a largura e a altura
arredondam para par cada uma por sua conta), contra os 3,16x que o
`processa.sh` corrigia em 05/09. Um rosto de 700 px sai 1,3 px mais largo.

A curva entre dois enquadramentos é smoothstep (3p²-2p³): movimento que
começa e termina na velocidade máxima lê como corte mal feito.

Formato do arquivo de câmera — TSV, uma linha por enquadramento:

    # t      x     y     z     trans
    0.000    1080  1920  1.00  0
    9.660    1400  2280  2.00  0.90

  t      instante em que o enquadramento está ESTABELECIDO, em segundos
         relativos ao início do trecho
  x, y   o ponto do master que fica no centro da tela, em pixels do quadro
         JÁ GIRADO (2160x3840 neste material, não 3840x2160)
  z      1,00 = quadro inteiro; 2,00 = recorte 1:1 (o máximo honesto aqui)
  trans  duração da transição que CHEGA neste enquadramento. 0 = corte seco,
         que o script resolve como um frame — é o que corte seco significa.

Fora das bordas do quadro o crop é preso com max/min: pedir o rosto centrado
quando ele está a 850 px do topo não estoura, encosta no topo. O
enquadramento resultante é o que o preview mostra, então valide no frame.
"""
import argparse
import sys


def le_camera(caminho):
    kfs = []
    with open(caminho, encoding="utf-8") as f:
        for n, linha in enumerate(f, 1):
            linha = linha.split("#")[0].strip()
            if not linha:
                continue
            campos = linha.split()
            if len(campos) < 4:
                sys.exit(f"{caminho}:{n}: esperado 't x y z [trans]', veio: {linha!r}")
            t, x, y, z = (float(c) for c in campos[:4])
            trans = float(campos[4]) if len(campos) > 4 else 0.0
            kfs.append({"t": t, "x": x, "y": y, "z": z, "trans": trans})
    if not kfs:
        sys.exit(f"{caminho}: nenhum enquadramento")
    kfs.sort(key=lambda k: k["t"])
    return kfs


def nos(kfs, chave, tfim, quadro):
    """(t, valor) com os platôs duplicados, para interpolar só nas transições."""
    saida = [(kfs[0]["t"], kfs[0][chave])]
    for ant, kf in zip(kfs, kfs[1:]):
        tr = max(kf["trans"], quadro)
        inicio = kf["t"] - tr
        if inicio < ant["t"] - 1e-6:
            sys.exit(
                f"transição de {tr:.3f}s chegando em {kf['t']:.3f}s invade o "
                f"enquadramento anterior, que só se estabelece em {ant['t']:.3f}s"
            )
        saida.append((inicio, ant[chave]))
        saida.append((kf["t"], kf[chave]))
    saida.append((max(tfim, kfs[-1]["t"]), kfs[-1][chave]))
    return saida


def por_partes(ns):
    """Cadeia de if() com smoothstep dentro de cada transição."""
    e = f"{ns[-1][1]:.4f}"
    for (ta, va), (tb, vb) in reversed(list(zip(ns, ns[1:]))):
        if abs(vb - va) < 1e-9 or tb - ta < 1e-9:
            seg = f"{va:.4f}"
        else:
            p = f"((t-{ta:.4f})/{tb - ta:.4f})"
            seg = f"({va:.4f}+{vb - va:.4f}*{p}*{p}*(3-2*{p}))"
        e = f"if(lt(t,{tb:.4f}),{seg},{e})"
    return f"if(lt(t,{ns[0][0]:.4f}),{ns[0][1]:.4f},{e})"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("camera", help="TSV de enquadramentos")
    ap.add_argument("--master-w", type=int, required=True,
                    help="largura do master JÁ GIRADO")
    ap.add_argument("--master-h", type=int, required=True)
    ap.add_argument("--saida-w", type=int, required=True)
    ap.add_argument("--saida-h", type=int, required=True)
    ap.add_argument("--fps", type=float, default=60.0)
    ap.add_argument("--duracao", type=float, required=True)
    ap.add_argument("--relatorio", action="store_true",
                    help="descreve os enquadramentos no stderr")
    a = ap.parse_args()

    prop_m = a.master_w / a.master_h
    prop_s = a.saida_w / a.saida_h
    if abs(prop_m - prop_s) > 0.005:
        sys.exit(f"master {prop_m:.4f} e saída {prop_s:.4f} têm proporções "
                 f"diferentes; esta câmera só recorta, não põe barra")

    z_max = a.master_w / a.saida_w
    kfs = le_camera(a.camera)
    for kf in kfs:
        if kf["z"] > z_max + 1e-6:
            sys.exit(f"zoom {kf['z']:.2f} em t={kf['t']:.2f}s amplia: o máximo "
                     f"sem ampliar é {z_max:.2f} ({a.master_w}/{a.saida_w})")
        if kf["z"] < 1.0 - 1e-6:
            sys.exit(f"zoom {kf['z']:.2f} em t={kf['t']:.2f}s é menor que o "
                     f"quadro inteiro; não há imagem para preencher")

    quadro = 1.0 / a.fps
    ez = por_partes(nos(kfs, "z", a.duracao, quadro))
    ex = por_partes(nos(kfs, "x", a.duracao, quadro))
    ey = por_partes(nos(kfs, "y", a.duracao, quadro))

    # ceil para par: o floor devolvia 1078 num zoom de 0,999 e o crop de 1080
    # morre sem imagem.
    w = f"2*ceil({a.saida_w}*({ez})/2)"
    h = f"2*ceil({a.saida_h}*({ez})/2)"
    # a largura repetida, não lida do link: ver o cabeçalho.
    filtro = (
        f"scale=w='{w}':h='{h}':eval=frame:flags=bicubic,"
        f"crop={a.saida_w}:{a.saida_h}"
        f":'max(0,min(({w})-{a.saida_w},({ex})*({w})/{a.master_w}-{a.saida_w // 2}))'"
        f":'max(0,min(({h})-{a.saida_h},({ey})*({h})/{a.master_h}-{a.saida_h // 2}))'"
    )
    print(filtro)

    if a.relatorio:
        print(f"    câmera: {len(kfs)} enquadramentos, zoom máximo honesto "
              f"{z_max:.2f}x", file=sys.stderr)
        for kf in kfs:
            j_w = a.master_w / kf["z"]
            j_h = a.master_h / kf["z"]
            x0 = max(0.0, min(a.master_w - j_w, kf["x"] - j_w / 2))
            y0 = max(0.0, min(a.master_h - j_h, kf["y"] - j_h / 2))
            preso = ""
            if abs(x0 - (kf["x"] - j_w / 2)) > 0.5:
                preso += " x-preso"
            if abs(y0 - (kf["y"] - j_h / 2)) > 0.5:
                preso += " y-preso"
            modo = "corte seco" if kf["trans"] <= 0 else f"{kf['trans']:.2f}s"
            print(f"    {kf['t']:7.3f}s  z={kf['z']:.2f}  centro "
                  f"({kf['x']:.0f},{kf['y']:.0f})  janela "
                  f"{j_w:.0f}x{j_h:.0f} em ({x0:.0f},{y0:.0f})  "
                  f"{modo}{preso}", file=sys.stderr)


if __name__ == "__main__":
    main()
