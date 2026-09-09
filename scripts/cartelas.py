#!/usr/bin/env python3
"""Desenha as cartelas de abertura e de créditos como PNG com canal alfa.

Quem sobrepõe é o ffmpeg (scripts/cartelas.sh); aqui só se desenha.

Por que PNG e não `drawtext`: a Charter é Type1 (.pfb), que o Pillow carrega e
o drawtext não trata bem, e o parser do filtergraph ainda descarta o rótulo
inteiro diante de um '%' solto, com um warning que passa despercebido. Desenhar
fora e sobrepor tira as duas armadilhas do caminho.

Nenhuma cor, tamanho, margem ou fonte é escrita aqui dentro: tudo vem de
marca/tokens.toml. A margem lateral e a inferior vêm de `formato.<fmt>`, que é
a safe area já decidida — a cartela não pode cair atrás dos botões da
plataforma, e esse número mora em um lugar só.

Sobre imagem, todo texto é creme. O acento vive na barra, no chip e no fio.
É a regra medida em docs/04-identidade.md, e a cartela não abre exceção.

Uso:
    python scripts/cartelas.py \
        --titulo "A Hard Day's Night" \
        --autoria "Lennon-McCartney" --ano 1964 \
        --papeis "produção, mixagem e execução" \
        --prefixo work/improviso_3_cover
"""
import argparse
import pathlib
import tomllib

from PIL import Image, ImageDraw, ImageFont

RAIZ = pathlib.Path(__file__).resolve().parent.parent
FONTES_INTER = pathlib.Path("/usr/share/fonts/opentype/inter")


# ---------------------------------------------------------------------------
# Tokens e fontes
# ---------------------------------------------------------------------------

# Medidas em PIXEL, as únicas que acompanham a resolução de saída.
#
# Cartela desenhada em 1080x1920 e escalada 2x para um vídeo 4K entra com o
# texto borrado — e logo na parte do quadro que é tipografia pura, que é
# onde a perda mais aparece. Então a cartela se DESENHA na resolução do
# vídeo, e o que muda é o token, não o PNG.
#
# O que NÃO está aqui é tão importante quanto o que está: `duracao`,
# `atraso`, os `fade_*` e `scrim_forca` são tempo e alfa, e `entrelinha` é
# múltiplo do tamanho da fonte. Escalar qualquer um deles mudaria a
# montagem em vez da resolução.
_PX_FORMATO = ("largura", "altura", "tamanho", "contorno", "sombra",
               "margem_lateral", "margem_inferior")
_PX_CARTELA = ("barra_largura", "barra_gap", "contorno",
               "scrim_rampa", "scrim_folga")
_PX_SECAO = ("tamanho_titulo", "tamanho_credito", "tamanho_chip",
             "chip_tracking", "tamanho_etiqueta", "tamanho_nome",
             "tamanho_handle", "etiqueta_tracking", "fio_largura")


def tokens(largura: int | None = None, fmt: str = "9x16") -> dict:
    """Os tokens da marca, opcionalmente redimensionados para `largura`.

    Sem argumento devolve o arquivo como está — é o que todo chamador
    antigo recebe, e por isso nada muda para quem não pede escala.

    Com `largura`, todas as medidas em pixel são multiplicadas por
    largura/largura_do_formato. Ver "Resolução de entrega" no CLAUDE.md.
    """
    with (RAIZ / "marca" / "tokens.toml").open("rb") as f:
        t = tomllib.load(f)
    if largura is None:
        return t

    base = t["formato"][fmt]["largura"]
    if largura == base:
        return t
    k = largura / base

    def esc(v):
        return round(v * k) if isinstance(v, int) else v * k

    f_ = t["formato"][fmt]
    for campo in _PX_FORMATO:
        if campo in f_:
            f_[campo] = esc(f_[campo])
    c = t["cartela"]
    for campo in _PX_CARTELA:
        if campo in c:
            c[campo] = esc(c[campo])
    for secao, sub in c.items():
        if isinstance(sub, dict):
            for campo in _PX_SECAO:
                if campo in sub:
                    sub[campo] = esc(sub[campo])
    return t


def fonte(caminho: str, tam: int) -> ImageFont.FreeTypeFont:
    p = pathlib.Path(caminho) if caminho.startswith("/") else FONTES_INTER / caminho
    if not p.exists():
        raise SystemExit(f"fonte não encontrada: {p}")
    return ImageFont.truetype(str(p), tam)


def faces(t: dict) -> dict:
    """As três faces que a cartela usa, resolvidas pelos tokens.

    A Charter carrega marca e títulos; a Inter fica no que é pequeno — etiqueta
    em caixa alta, chip e handle. É a mesma divisão de papéis do marca.py.
    """
    tip = t["tipografia"]
    return {
        "serif_bold": tip["marca_arquivo"],
        "serif": tip["marca_regular"],
        "serif_it": tip["marca_italico"],
        "sans_bold": "Inter-Bold.otf",
        "sans_medio": "Inter-Medium.otf",
    }


def larg(d: ImageDraw.ImageDraw, txt: str, f) -> int:
    return int(d.textlength(txt, font=f))


# ---------------------------------------------------------------------------
# Scrim
# ---------------------------------------------------------------------------

def scrim(img: Image.Image, topo_bloco: int, t: dict) -> Image.Image:
    """Escurece do bloco para baixo, com rampa em cima e nada de borda dura.

    É a peça que carrega o contraste. Medido neste material: o vídeo cru não
    tem nenhuma faixa horizontal onde branco puro alcance 4,5:1 — o p95 de
    luminância das bandas vai de 0,33 a 0,84, o que dá de 1,2:1 a 2,7:1 em
    todo lugar. Clarear a letra não tem para onde ir; o que falta é escurecer
    o fundo, e é o que o scrim faz.

    Abaixo do bloco o scrim segue cheio até a base do quadro. Aquela faixa é
    justamente a que a interface do Reels e do Shorts cobre, então escurecê-la
    não custa imagem nenhuma.
    """
    c = t["cartela"]
    forca, rampa = c["scrim_forca"], c["scrim_rampa"]
    w, h = img.size
    alfa = Image.new("L", (w, h), 0)
    px = alfa.load()
    inicio = topo_bloco - rampa
    for y in range(max(0, inicio), h):
        if y >= topo_bloco:
            v = 1.0
        else:
            v = (y - inicio) / rampa
        col = int(255 * forca * v ** 1.4)
        for x in range(w):
            px[x, y] = col
    camada = Image.new("RGBA", (w, h), t["paleta"]["fundo"])
    camada.putalpha(alfa)
    return Image.alpha_composite(img, camada)


# ---------------------------------------------------------------------------
# Blocos de texto
#
# Cada elemento é um dicionário; a cartela é montada em duas passadas: a
# primeira só mede a altura total, a segunda desenha com o bloco já ancorado
# na base da safe area. Assim o layout não depende de contar linhas na mão.
# ---------------------------------------------------------------------------

def _texto(txt, f, altura=None):
    return {"tipo": "texto", "txt": txt, "f": f,
            "alt": altura if altura is not None else int(f.size * 1.14)}


def _tracking(txt, f, esp, altura=None):
    return {"tipo": "tracking", "txt": txt, "f": f, "esp": esp,
            "alt": altura if altura is not None else int(f.size * 1.6)}


def _chip(txt, f, esp, altura):
    return {"tipo": "chip", "txt": txt, "f": f, "esp": esp, "alt": altura}


def _fio(largura_px, altura, comprimento):
    return {"tipo": "fio", "w": largura_px, "alt": altura, "comp": comprimento}


def _espaco(altura):
    return {"tipo": "espaco", "alt": altura}


def desenha_tracking(d, xy, txt, f, esp, fill, contorno, cor_contorno):
    x, y = xy
    for ch in txt:
        d.text((x, y), ch, font=f, fill=fill,
               stroke_width=contorno, stroke_fill=cor_contorno)
        x += larg(d, ch, f) + esp
    return x


def largura_tracking(d, txt, f, esp):
    return sum(larg(d, ch, f) + esp for ch in txt) - esp if txt else 0


def _pinta(img, t, fmt, elementos, y0, sem_texto):
    """Pinta a tinta — barra, chip, texto e fio — com o bloco começando em y0."""
    p, c = t["paleta"], t["cartela"]
    f = t["formato"][fmt]
    x_marg = f["margem_lateral"]
    barra_w, gap = c["barra_largura"], c["barra_gap"]
    x_txt = x_marg + barra_w + gap
    contorno, cor_contorno = c["contorno"], p["fundo"]
    total = sum(e["alt"] for e in elementos)
    d = ImageDraw.Draw(img)

    # a barra de acento acompanha o bloco inteiro: é o mesmo elemento do
    # lockup e da thumbnail, e é o único lugar em que o acento pode viver
    # sobre foto — como forma, nunca como letra.
    d.rectangle([x_marg, y0, x_marg + barra_w, y0 + total - 8],
                fill=p["acento_claro"])

    y = y0
    for e in elementos:
        if sem_texto and e["tipo"] in ("texto", "tracking", "chip"):
            y += e["alt"]
            continue
        if e["tipo"] == "texto":
            d.text((x_txt, y), e["txt"], font=e["f"], fill=p["texto"],
                   stroke_width=contorno, stroke_fill=cor_contorno)
        elif e["tipo"] == "tracking":
            desenha_tracking(d, (x_txt, y), e["txt"], e["f"], e["esp"],
                             p["texto"], contorno, cor_contorno)
        elif e["tipo"] == "chip":
            # o acento é FUNDO, o texto é creme: terracota tem luminância
            # 0,146 e mede 4,8:1 com creme por cima. O inverso não fecha.
            tw = largura_tracking(d, e["txt"], e["f"], e["esp"])
            d.rectangle([x_txt - 12, y - 6,
                         x_txt + tw + 14, y + e["f"].size + 12],
                        fill=p["acento"])
            desenha_tracking(d, (x_txt, y), e["txt"], e["f"], e["esp"],
                             p["texto"], 0, cor_contorno)
        elif e["tipo"] == "fio":
            d.rectangle([x_txt, y, x_txt + e["comp"], y + e["w"]],
                        fill=p["acento_claro"])
        y += e["alt"]


def monta(t: dict, fmt: str, elementos: list, sem_texto: bool = False) -> Image.Image:
    """Desenha os elementos ancorados na base da safe area do formato.

    A âncora é a CAIXA DE TINTA medida, não a soma das alturas de linha. A
    diferença não é acadêmica: somando as alturas, a cartela de abertura deste
    episódio pousava 4 px dentro da safe area — o descendente do 'y' da última
    linha mais os 2 px de contorno, que nenhuma altura de linha prevê. Quatro
    pixels não se veem numa prova, e o modo de falha é justamente esse: o
    texto some atrás dos botões do Reels sem nada acusar. Por isso o bloco é
    desenhado, medido e só então posicionado.

    `sem_texto` devolve a mesma peça sem uma letra — a camada contra a qual o
    texto é medido em scripts/valida-cartela.py. Sem ela a medição teria de
    supor a cor do fundo, e supor é o que este projeto não faz.
    """
    p, c = t["paleta"], t["cartela"]
    f = t["formato"][fmt]
    w, h = f["largura"], f["altura"]
    y_base = h - f["margem_inferior"]

    # 1ª passada: pinta com a âncora ingênua só para medir a caixa real.
    # A caixa medida é sempre a da peça COM texto — senão a versão sem texto
    # (que o validador usa como referência) sairia deslocada da versão real,
    # e as duas máscaras deixariam de casar.
    provisorio = y_base - sum(e["alt"] for e in elementos)
    prova = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    _pinta(prova, t, fmt, elementos, provisorio, sem_texto=False)
    caixa = prova.getbbox()
    if caixa is None:
        raise SystemExit("a cartela saiu vazia")
    _, topo, _, fundo_tinta = caixa

    y0 = provisorio - (fundo_tinta - y_base)
    topo += y0 - provisorio
    if topo - c["scrim_folga"] < 0:
        raise SystemExit("a cartela não cabe acima da safe area — reduza texto "
                         "ou os tamanhos em marca/tokens.toml")

    # 2ª passada: o scrim nasce do topo da tinta medida, não de uma estimativa.
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    img = scrim(img, topo - c["scrim_folga"], t)
    _pinta(img, t, fmt, elementos, y0, sem_texto)
    return img


# ---------------------------------------------------------------------------
# As duas cartelas
# ---------------------------------------------------------------------------

def abertura(t, fmt, titulo, autoria, ano, rotulo, sem_texto=False):
    """Discreta: chip, título e uma linha de crédito. Nada mais.

    Cabe perguntar por que tão pouco. Porque é abertura de um vídeo de 60s: o
    espectador decide ficar nos primeiros segundos, e qualquer linha a mais
    disputa atenção com a música. O que um cover precisa declarar é o que a
    música é e de quem ela é — o resto vai nos créditos.
    """
    c, ca = t["cartela"], t["cartela"]["abertura"]
    fc = faces(t)
    el = c["entrelinha"]
    f_chip = fonte(fc["sans_bold"], ca["tamanho_chip"])
    f_tit = fonte(fc["serif_bold"], ca["tamanho_titulo"])
    f_cred = fonte(fc["serif_it"], ca["tamanho_credito"])

    credito = f"{autoria} · {ano}" if ano else autoria
    elementos = [
        _chip(rotulo.upper(), f_chip, ca["chip_tracking"],
              int(f_chip.size * 2.2)),
        _texto(titulo, f_tit, int(f_tit.size * el)),
        _espaco(int(f_cred.size * 0.30)),
        _texto(credito, f_cred, int(f_cred.size * el)),
    ]
    return monta(t, fmt, elementos, sem_texto)


def creditos(t, fmt, titulo, autoria, papeis, sem_texto=False):
    """A obra em cima, quem a executou embaixo, separados por um fio.

    A ordem não é decorativa: num cover a obra é de outra pessoa e o crédito de
    composição é atribuição factual, não cortesia. Ele vem primeiro, e o fio
    marca que o que vem abaixo é de outra natureza — execução, não autoria.
    """
    c, cc = t["cartela"], t["cartela"]["creditos"]
    m, fc = t["marca"], faces(t)
    el = c["entrelinha"]
    f_tit = fonte(fc["serif_bold"], cc["tamanho_titulo"])
    f_cred = fonte(fc["serif_it"], cc["tamanho_credito"])
    f_et = fonte(fc["sans_bold"], cc["tamanho_etiqueta"])
    f_nome = fonte(fc["serif_bold"], cc["tamanho_nome"])

    elementos = [
        _texto(titulo, f_tit, int(f_tit.size * el)),
        _espaco(int(f_cred.size * 0.24)),
        _texto(f"composição: {autoria}", f_cred, int(f_cred.size * el)),
        _espaco(int(f_tit.size * 0.85)),
        _fio(cc["fio_largura"], int(f_et.size * 1.9), int(f_tit.size * 3.4)),
        _tracking(papeis.upper(), f_et, cc["etiqueta_tracking"],
                  int(f_et.size * 1.7)),
        # Uma linha só de identidade — ver [cartela.creditos] assinatura.
        _texto(cc["assinatura"], f_nome, int(f_nome.size * el)),
    ]
    return monta(t, fmt, elementos, sem_texto)


# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--titulo", required=True, help="título da obra")
    ap.add_argument("--autoria", required=True,
                    help="quem compôs, como deve aparecer no crédito")
    ap.add_argument("--ano", default="", help="ano da obra (opcional)")
    ap.add_argument("--rotulo", default="cover",
                    help="o chip da abertura (ex: cover, estudo, original)")
    ap.add_argument("--papeis", default="produção, mixagem e execução",
                    help="o que o autor do canal fez nesta gravação")
    ap.add_argument("--formato", default="9x16", help="chave em [formato] dos tokens")
    ap.add_argument("--prefixo", required=True,
                    help="prefixo dos PNG de saída (sem extensão)")
    ap.add_argument("--sem-texto", action="store_true",
                    help="gera também a camada sem letra nenhuma, que o\nvalidador usa como fundo de referência")
    args = ap.parse_args()

    t = tokens()
    if args.formato not in t["formato"]:
        raise SystemExit(f"formato desconhecido: {args.formato}")

    pref = pathlib.Path(args.prefixo)
    pref.parent.mkdir(parents=True, exist_ok=True)
    saidas = []
    for st in ([False, True] if args.sem_texto else [False]):
        suf = ".sem-texto.png" if st else ".png"
        saidas.append((f"{pref}.abertura{suf}",
                       abertura(t, args.formato, args.titulo, args.autoria,
                                args.ano, args.rotulo, st)))
        saidas.append((f"{pref}.creditos{suf}",
                       creditos(t, args.formato, args.titulo, args.autoria,
                                args.papeis, st)))
    for nome, img in saidas:
        img.save(nome)
        print(f"  {nome}  {img.width}x{img.height} RGBA")


if __name__ == "__main__":
    main()
