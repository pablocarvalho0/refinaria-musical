#!/usr/bin/env python3
"""Carrossel de Instagram (1080x1350) a partir de marca/tokens.toml.

Mesma regra do marca.py, do qual este script reusa tudo o que desenha: nenhuma
cor, fonte ou margem é escrita aqui dentro. Trocar o acento no .toml troca o
carrossel inteiro.

O TEXTO fica no topo do arquivo, em SLIDES, pelo mesmo motivo que as regras de
fecho de cue ficam no topo do legenda.py: é o que se ajusta depois de ver na
tela, e ter que procurar dentro de uma função para mexer numa vírgula é o tipo
de atrito que faz ninguém ajustar.

O post é um PROJETO, como um episódio: tudo o que ele gera mora em
`out/<projeto>/`, e quem resolve a pasta é o `pasta_projeto`, nunca um caminho
montado aqui dentro. Ele não é arte de marca — `out/marca/` guarda logo e
gabarito, coisas que servem a todos os episódios; um carrossel é entregável de
uma publicação só, e some junto com ela quando for arquivada.

Uso:
    python scripts/carrossel.py out/ep00/ep00_audio.mp4 --t 145
    python scripts/carrossel.py <video> --t 145 --so 1        # regera 1 slide
    python scripts/carrossel.py <video> --projeto post-ouvido # outra publicação
"""
import argparse
import pathlib
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from marca import (  # noqa: E402
    BOLD, CHARTER, CHARTER_BOLD, cobre, fonte, frame_do_video,
    larg, quebra, tokens,
)
from projeto import pasta_projeto, resumo  # noqa: E402

LARGURA, ALTURA = 1080, 1350
PROJETO_PADRAO = "post-carrossel"

# ---------------------------------------------------------------------------
# O conteúdo.
#
# `ground` decide o par de cores, e o par NÃO é escolha de gosto: sobre escuro
# o acento é o salmão (8,7:1) e sobre claro é o terracota (5,0:1). Trocar um
# pelo outro quebra o contraste — está medido em docs/04-identidade.md.
#
# O ritmo é de três movimentos, não de alternância slide a slide: a prova
# acontece no escuro, a explicação no papel, o fecho volta ao escuro. Piscar
# claro/escuro a cada arrasto cansa e não significa nada.
#
# A âncora do slide 2 é "Parabéns pra você" de propósito: o benchmarking (Rick
# Beato, Jens Larsen) diz para ancorar no que a pessoa já conhece, e esta é a
# única melodia que dá para assumir que o Brasil inteiro sabe de cor. O leitor
# faz o teste na própria cabeça enquanto rola — a prova é dele, não minha.
# ---------------------------------------------------------------------------
SLIDES = [
    dict(
        tipo="capa",
        etiqueta="harmonia funcional",
        titulo="Não existe\nouvido ruim.",
        corpo="E dá para provar em seis slides.",
    ),
    dict(
        tipo="texto", ground="fundo",
        titulo="Cante “Parabéns\npra você” — e pare\numa nota antes do fim.",
        corpo="Vai. Agora. Em voz alta ou só na cabeça, tanto faz.",
    ),
    dict(
        tipo="texto", ground="fundo",
        titulo="Incomodou.",
        corpo="A frase não terminou, e o seu corpo sabe disso. Ninguém te "
              "ensinou essa regra. Você não decorou acorde nenhum. Ainda "
              "assim você sabe.",
    ),
    dict(
        tipo="texto", ground="papel",
        etiqueta="o que isso quer dizer",
        titulo="Antes de dizer\n“mamãe”, você já\nentendia entonação.",
        corpo="A música é a língua materna da humanidade. Ninguém chega aqui "
              "do zero.",
    ),
    dict(
        tipo="texto", ground="papel",
        etiqueta="então pra que serve a teoria",
        titulo="Teoria não é\num livro de regras.\nÉ a gramática\nda emoção.",
        corpo="Ninguém aprende gramática para aprender a falar. Aprende para "
              "entender como está falando — e para se expressar com clareza.",
    ),
    dict(
        tipo="texto", ground="papel",
        etiqueta="o que muda",
        titulo="Você para de esperar\no arrepio acontecer\npor sorte.",
        corpo="Passa a saber de onde ele vem. E, o que importa mais, passa a "
              "conseguir provocá-lo de propósito.",
    ),
    dict(
        tipo="texto", ground="fundo",
        titulo="Não existe talento\ndivino exclusivo.",
        corpo="Existe o ouvinte que sente, mas ainda não se permitiu olhar os "
              "padrões por trás da sensação. Meu trabalho não é te ensinar a "
              "sentir. É dar nome ao que você já sente.",
    ),
    dict(
        tipo="cta", ground="fundo",
        etiqueta="começa agora",
        titulo="Harmonia funcional,\ndo começo.",
        corpo="47 episódios. Sete anos de estudo virando playlist.\n"
              "Salva esse post — o primeiro sai em breve.",
    ),
]

# A legenda do post mora aqui, junto dos slides, e não num .txt solto: os dois
# contam a MESMA história e desencontrá-los é o tipo de erro que ninguém vê —
# o slide fala de "Parabéns pra você" e a legenda, editada noutro dia, fala de
# outra coisa. Um comando regenera o post inteiro.
#
# A primeira linha tem que se sustentar sozinha: o feed trunca perto de 125
# caracteres, e é só isso que a maioria vai ler.
LEGENDA = """
Cante "Parabéns pra você" e pare uma nota antes do fim. Incomodou, né? Pronto: você entende harmonia.

Você não decorou regra nenhuma. Ninguém te sentou numa cadeira para explicar tensão e resolução. Ainda assim o seu corpo sabe, com certeza absoluta, que aquela frase não terminou.

É isso que eu quero dizer quando digo que não existe ouvido ruim.

A música é a língua materna da humanidade — antes de aprender a falar "mamãe", você já entendia ritmo e entonação. O que a maioria das pessoas não tem não é sensibilidade. É vocabulário.

E é aí que a teoria entra, mas não do jeito que te venderam. Teoria musical não é um livro de regras e proibições. É a gramática da emoção. Ninguém aprende gramática para aprender a falar — aprende para entender como está falando, e para se expressar com mais clareza.

O que muda quando você tem os nomes: você para de esperar o arrepio acontecer por sorte. Passa a saber de onde ele vem. E, o que importa mais, passa a conseguir provocá-lo de propósito.

Não existe talento divino exclusivo. Existe o ouvinte que sente, mas ainda não se permitiu olhar os padrões por trás da sensação.

Meu trabalho não é te ensinar a sentir. É dar nome ao que você já sente.

Salva esse post. Vem aí uma playlist de harmonia funcional do zero — 47 episódios, sete anos de estudo virando vídeo.

Qual foi a última vez que uma música te deu arrepio e você não soube dizer por quê? Conta nos comentários que eu explico o que estava acontecendo ali.

#harmoniafuncional #teoriamusical #violao #musicabrasileira #improvisacao #estudodemusica #harmonia #violaobrasileiro
"""

# Tipografia da peça. Charter carrega título e corpo (é do mundo do guia
# escrito); a Inter fica na etiqueta e no rodapé, que são pequenos.
TAM_TITULO = 84          # teto; encolhe sozinho até TAM_TITULO_MIN se precisar
TAM_TITULO_MIN = 52
TAM_CORPO = 40
TAM_ETIQUETA = 24
TAM_RODAPE = 26
ENTRELINHA_TITULO = 1.12
ENTRELINHA_CORPO = 1.36
MARGEM = 84
RESPIRO_ETIQUETA = 52    # da base da etiqueta ao topo do título
RESPIRO_CORPO = 34       # do fim do título ao começo do corpo
TRACKING = 3             # px extra entre caracteres da etiqueta em caixa alta
FOTO_ALTURA = 0.58       # fração da altura na capa, igual ao post de feed


def cores(t: dict, ground: str) -> dict:
    """O par de cores do ground. Ver a nota em SLIDES."""
    p = t["paleta"]
    if ground == "papel":
        return dict(fundo=p["papel"], texto=p["texto_tinta"], acento=p["acento"],
                    fraco="#6B6055", fio="#DDD5CB")
    return dict(fundo=p["fundo"], texto=p["texto"], acento=p["acento_claro"],
                fraco=p["texto_fraco"], fio="#3A332B")


def etiqueta(d, x, y, txt, cor, tam=TAM_ETIQUETA):
    """Caixa alta com tracking, como as do guia escrito."""
    f = fonte(BOLD, tam)
    for ch in txt.upper():
        d.text((x, y), ch, font=f, fill=cor)
        x += larg(d, ch, f) + TRACKING
    return int(tam * 1.9)


def quebra_titulo(d, txt, f, limite):
    """Quebra automática, respeitando os '\\n' escritos à mão.

    A quebra automática enche a linha e sobra o resto: "Não existe ouvido /
    ruim." deixa uma palavra órfã, e no título grande isso salta aos olhos. Um
    '\\n' no SLIDES diz onde a frase respira — é a mesma ideia do
    `ajusta_fronteiras` do legenda.py, só que aqui quem sabe o sintagma é
    quem escreveu, e não vale adivinhar por classe gramatical num texto de
    seis palavras.
    """
    linhas = []
    for pedaco in txt.split("\n"):
        linhas += quebra(d, pedaco, f, limite)
    return linhas


def bloco_titulo(d, txt, limite):
    """Escolhe o maior corpo de fonte em que o título cabe.

    Duas condições, e a segunda é a que importa: além do teto de 5 linhas,
    **cada pedaço separado por '\\n' precisa caber numa linha só**. Sem isso o
    '\\n' vira sugestão — a quebra automática entra por cima e devolve
    exatamente a órfã que a quebra manual existia para evitar ("Cante
    “Parabéns pra / você”"). Quem escreveu o '\\n' pediu aquela linha; se ela
    não cabe, quem cede é o corpo da fonte, não a intenção.
    """
    pedacos = [p for p in txt.split("\n") if p]
    tam = TAM_TITULO
    while tam > TAM_TITULO_MIN:
        f = fonte(CHARTER_BOLD, tam)
        linhas = quebra_titulo(d, txt, f, limite)
        se_respeita = all(len(quebra(d, p, f, limite)) == 1 for p in pedacos)
        if len(linhas) <= 5 and se_respeita:
            return f, linhas
        tam -= 4
    f = fonte(CHARTER_BOLD, TAM_TITULO_MIN)
    return f, quebra_titulo(d, txt, f, limite)


def rodape(d, c, n, total, t):
    """Fio, assinatura e o contador. O contador não é enfeite: saber que
    faltam três slides é o que faz a pessoa continuar arrastando."""
    m = t["marca"]
    y = ALTURA - 112
    d.line([(MARGEM, y), (LARGURA - MARGEM, y)], fill=c["fio"], width=1)
    f = fonte(BOLD, TAM_RODAPE)
    d.text((MARGEM, y + 26), m["handle"], font=f, fill=c["fraco"])
    marcador = f"{n}/{total}"
    d.text((LARGURA - MARGEM - larg(d, marcador, f), y + 26), marcador,
           font=f, fill=c["acento"])


def slide_capa(t, s, video, tempo, n, total):
    """Capa: foto em cima, tipografia sobre papel embaixo — a composição do
    post de feed, que é onde a direção do guia cabe inteira."""
    c = cores(t, "papel")
    img = Image.new("RGB", (LARGURA, ALTURA), c["fundo"])
    import tempfile
    with tempfile.TemporaryDirectory() as dtmp:
        f = f"{dtmp}/f.png"
        frame_do_video(video, tempo, f)
        foto = cobre(Image.open(f).convert("RGB"), LARGURA, int(ALTURA * FOTO_ALTURA))
    img.paste(foto, (0, 0))
    d = ImageDraw.Draw(img)

    y = int(ALTURA * FOTO_ALTURA)
    d.rectangle([0, y, LARGURA, y + 7], fill=c["acento"])
    y += 58

    limite = LARGURA - 2 * MARGEM
    y += etiqueta(d, MARGEM, y, s["etiqueta"], c["acento"])
    f_t, linhas = bloco_titulo(d, s["titulo"], limite)
    for l in linhas:
        d.text((MARGEM, y), l, font=f_t, fill=c["texto"])
        y += int(f_t.size * ENTRELINHA_TITULO)
    y += RESPIRO_CORPO
    f_c = fonte(CHARTER, TAM_CORPO)
    for l in quebra(d, s["corpo"], f_c, limite):
        d.text((MARGEM, y), l, font=f_c, fill=c["fraco"])
        y += int(TAM_CORPO * ENTRELINHA_CORPO)

    rodape(d, c, n, total, t)
    return img


def slide_texto(t, s, n, total):
    """Slide de tipografia pura, com o bloco centrado na vertical.

    Centrar e não alinhar no topo: os slides têm quantidades de texto muito
    diferentes (de uma palavra a quatro linhas), e o topo fixo faz o slide
    curto parecer inacabado.
    """
    c = cores(t, s["ground"])
    img = Image.new("RGB", (LARGURA, ALTURA), c["fundo"])
    d = ImageDraw.Draw(img)
    limite = LARGURA - 2 * MARGEM

    # Mede primeiro, desenha depois — é o que permite centrar.
    partes = []
    if s.get("etiqueta"):
        partes.append(("etiqueta", s["etiqueta"], RESPIRO_ETIQUETA))
    f_t, linhas_t = bloco_titulo(d, s["titulo"], limite)
    alt_titulo = len(linhas_t) * int(f_t.size * ENTRELINHA_TITULO)
    f_c = fonte(CHARTER, TAM_CORPO)
    linhas_c = []
    for paragrafo in s.get("corpo", "").split("\n"):
        linhas_c += quebra(d, paragrafo, f_c, limite) if paragrafo else [""]
    alt_corpo = len(linhas_c) * int(TAM_CORPO * ENTRELINHA_CORPO)

    total_alt = alt_titulo + (RESPIRO_CORPO + alt_corpo if linhas_c else 0)
    if partes:
        total_alt += RESPIRO_ETIQUETA
    # O rodapé ocupa a base; o miolo se centra no que sobra.
    y = int((ALTURA - 150 - total_alt) / 2)

    if partes:
        etiqueta(d, MARGEM, y, s["etiqueta"], c["acento"])
        y += RESPIRO_ETIQUETA
    for l in linhas_t:
        d.text((MARGEM, y), l, font=f_t, fill=c["texto"])
        y += int(f_t.size * ENTRELINHA_TITULO)
    if linhas_c:
        y += RESPIRO_CORPO
        for l in linhas_c:
            d.text((MARGEM, y), l, font=f_c, fill=c["fraco"])
            y += int(TAM_CORPO * ENTRELINHA_CORPO)

    rodape(d, c, n, total, t)
    return img


def slide_cta(t, s, n, total):
    """O fecho leva a barra do lockup à esquerda: é o mesmo elemento gráfico
    do logo, da cartela e da thumbnail, e é o que assina a peça."""
    c = cores(t, s["ground"])
    img = slide_texto(t, s, n, total)
    d = ImageDraw.Draw(img)
    barra = t["cartela"]["barra_largura"]
    d.rectangle([0, 0, barra, ALTURA], fill=c["acento"])
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video", help="de onde sai o frame da capa")
    ap.add_argument("--t", type=float, default=145.0, help="segundo do frame")
    ap.add_argument("--so", type=int, help="regera só este slide (1-based)")
    ap.add_argument("--projeto", default=PROJETO_PADRAO,
                    help="nome da publicação; vira a pasta em out/")
    a = ap.parse_args()

    # O projeto é a PUBLICAÇÃO, não o vídeo de onde sai o frame da capa. Por
    # isso o nome não é derivado de `a.video` — aquele caminho resolveria para
    # o episódio (ep00), e o carrossel iria parar na pasta dele. `--projeto`
    # entra como um caminho solto justamente para cair no degrau 4 do
    # projeto.py, e `$PROJETO` continua tendo a última palavra, como em todo
    # o resto do pipeline.
    #
    # O `resumo` vem ANTES do `pasta_projeto`: este cria a pasta, e o degrau 3
    # ("pasta existente que prefixa o nome") passaria então a achar a pasta que
    # ele mesmo acabou de criar. O nome sai igual dos dois jeitos, mas o degrau
    # impresso viraria sempre 3 — e essa linha existe para denunciar escrita no
    # lugar errado, então ela não pode mentir sobre como chegou lá.
    t = tokens()
    print(resumo(a.projeto))
    destino = pasta_projeto(a.projeto)
    nome = destino.name
    total = len(SLIDES)

    for i, s in enumerate(SLIDES, 1):
        if a.so and i != a.so:
            continue
        if s["tipo"] == "capa":
            img = slide_capa(t, s, a.video, a.t, i, total)
        elif s["tipo"] == "cta":
            img = slide_cta(t, s, i, total)
        else:
            img = slide_texto(t, s, i, total)
        caminho = destino / f"{nome}_{i:02d}.png"
        img.save(caminho, quality=95)
        print(f"  {caminho.name}  ({s['tipo']}, {s.get('ground', 'papel')})")

    if not a.so:
        leg = destino / f"{nome}.legenda-instagram.txt"
        leg.write_text(LEGENDA.lstrip("\n"), encoding="utf-8")
        print(f"  {leg.name}  (primeira linha: "
              f"{len(LEGENDA.lstrip(chr(10)).split(chr(10))[0])} caracteres)")

    print(f"==> {total} slides em out/{nome}/")


if __name__ == "__main__":
    main()
