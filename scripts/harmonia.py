#!/usr/bin/env python3
"""A legenda de harmonia: que seção é esta, que acordes, que funções.

Por que existe, e por que NÃO é reconhecimento de acordes. Este projeto já
descartou o autochord com número (25 classes a ~67%, sem sétimas nem
inversões). O que se faz aqui é outra coisa: as fronteiras de seção saem da
medição (novidade de Foote sobre croma e MFCC, em 5 escalas), a progressão
sai da cifra, e QUEM CASA UMA COISA COM A OUTRA É O AUTOR, ouvindo. O script
só desenha o que já foi decidido. Nada aqui adivinha.

Por que não usa o scrim das cartelas. A cartela fica 6 s na tela; esta
legenda fica ~45 dos 60,7 s do cover. O scrim de alfa 0,72 escureceria a
metade de baixo do quadro o vídeo quase inteiro — 884 mil pixels por frame,
medido — e é justamente ali que o violão aparece. Quem sustenta o contraste
aqui é o contorno, que este projeto já mediu em 11,5:1 no pior caso deste
mesmo episódio. Decidido pelo autor na tela em 06/09/2026.

Nem a Inter nem a Charter têm U+266D. Na primeira prova o ♭ saiu como caixa
vazia, sem erro nenhum — o modo de falha de sempre. O acidente sai de uma
face de queda, escalada pela ALTURA DE CAIXA ALTA da face principal, não
pelo tamanho nominal: as duas famílias têm métricas diferentes e casar o
tamanho nominal deixaria o bemol fora de escala.

Uso:
    python scripts/harmonia.py --cues cues.tsv --prefixo work/<ep>_harm

O TSV tem quatro colunas: entra, sai, seção, acordes, funções. Imprime, uma
por linha, as especificações `PNG:entra:sai` para o monta-cartelas.sh.
"""
import argparse
import csv
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from PIL import Image, ImageColor, ImageDraw, ImageFont

from cartelas import faces, fonte, tokens

# A face de queda existe só para ♭ e ♯. Se ela sumir do sistema, o script
# para — melhor do que voltar a desenhar a caixa vazia em silêncio.
QUEDA = "/usr/share/fonts/opentype/freefont/FreeSansBold.otf"
ACIDENTES = "♭♯"


def _caixa_alta(f):
    b = f.getbbox("H")
    return b[3] - b[1]


def _escreve(d, xy, txt, f, cor, contorno, cor_contorno):
    """Escreve txt; o acidente vem da face de queda, casado pela caixa alta."""
    x, y = xy
    base = f.getbbox("H")[3]
    fq = ImageFont.truetype(QUEDA, f.size)
    k = _caixa_alta(f) / max(1, _caixa_alta(fq))
    fq = ImageFont.truetype(QUEDA, max(1, int(round(f.size * k * 1.30))))
    for ch in txt:
        ff = fq if ch in ACIDENTES else f
        dy = base - ff.getbbox(ch)[3] if ch in ACIDENTES else 0
        d.text((x, y + dy), ch, font=ff, fill=cor,
               stroke_width=contorno, stroke_fill=cor_contorno)
        x += d.textlength(ch, font=ff)


def desenha(t, fmt, secao, acordes, funcoes, sem_texto=False):
    """`sem_texto` devolve a mesma peça sem uma letra — é a camada contra a
    qual o scripts/valida-cartela.py mede o texto. Sem ela a medição teria de
    supor a cor do fundo, e supor é o que este projeto não faz."""
    p, c = t["paleta"], t["cartela"]
    h = c["harmonia"]
    fc, f = faces(t), t["formato"][fmt]
    w, alt_q = f["largura"], f["altura"]
    x_marg, y_base = f["margem_lateral"], alt_q - f["margem_inferior"]

    linhas = [(secao.upper(), fonte(fc["sans_bold"], h["tamanho_secao"]),
               h["altura_secao"]),
              (acordes, fonte(fc["serif_bold"], h["tamanho_acorde"]),
               h["altura_acorde"]),
              (funcoes, fonte(fc["sans_bold"], h["tamanho_funcao"]),
               h["altura_funcao"])]
    if not secao:
        linhas = linhas[1:]
    alt = sum(a for _, _, a in linhas)

    img = Image.new("RGBA", (w, alt_q), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    y0 = y_base - alt
    # a barra de acento é a única coisa da marca que pode viver sobre foto —
    # como forma, nunca como letra. Mesma barra do lockup e das cartelas.
    d.rectangle([x_marg, y0, x_marg + c["barra_largura"], y0 + alt - 8],
                fill=p["acento_claro"])
    x_txt = x_marg + c["barra_largura"] + c["barra_gap"]
    y = y0
    for txt, ff, a in linhas:
        if not sem_texto:
            _escreve(d, (x_txt, y), txt, ff, p["texto"],
                     c["contorno"], ImageColor.getrgb(p["fundo"]))
        y += a
    return img


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cues", required=True,
                    help="TSV: entra, sai, seção, acordes, funções")
    ap.add_argument("--prefixo", required=True)
    ap.add_argument("--formato", default="9x16")
    a = ap.parse_args()

    if not pathlib.Path(QUEDA).exists():
        sys.exit(f"face de queda do acidente não encontrada: {QUEDA}")

    t = tokens()
    if "harmonia" not in t["cartela"]:
        sys.exit("falta [cartela.harmonia] em marca/tokens.toml")

    with open(a.cues, encoding="utf-8") as fh:
        linhas = [r for r in csv.reader(fh, delimiter="\t")
                  if r and not r[0].startswith("#")]

    specs = []
    for i, (entra, sai, secao, acordes, funcoes) in enumerate(linhas, 1):
        img = desenha(t, a.formato, secao.strip(), acordes.strip(), funcoes.strip())
        cx = img.getbbox()
        if cx is None:
            sys.exit(f"cue {i} saiu vazio")
        if cx[1] - 8 < 0:
            sys.exit(f"cue {i} não cabe acima da safe area")
        p = f"{a.prefixo}.{i:02d}.png"
        img.save(p)
        desenha(t, a.formato, secao.strip(), acordes.strip(), funcoes.strip(),
                sem_texto=True).save(f"{a.prefixo}.{i:02d}.sem-texto.png")
        print(f"    {p}  {secao or '(sem rótulo)'}: {acordes}", file=sys.stderr)
        specs.append(f"{p}:{float(entra):.3f}:{float(sai):.3f}")
    print("\n".join(specs))


if __name__ == "__main__":
    main()
