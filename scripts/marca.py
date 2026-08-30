#!/usr/bin/env python3
"""Gera as peças da identidade visual a partir de marca/tokens.toml.

Tudo o que sai daqui é derivado dos tokens: mudar a cor de acento no .toml
muda logo, thumbnail, post e story de uma vez. Nenhuma cor ou tamanho é
escrito aqui dentro.

As peças que levam imagem usam FRAMES REAIS do episódio, não fundo de estúdio.
É a única forma de ver se o texto sobrevive à parede branca estourada e ao
violão sunburst, que é onde a legenda já quase falhou (ver docs/04).

Uso:
    python scripts/marca.py logos
    python scripts/marca.py thumb out/ep00_audio.mp4 --t 12 \
        --titulo "Dominante secundária" --sub "o acorde que puxa" --ep 3
    python scripts/marca.py post out/ep00_audio.mp4 --t 12 --titulo "..."
    python scripts/marca.py story out/ep00_audio.mp4 --t 12 --titulo "..."
    python scripts/marca.py tudo out/ep00_audio.mp4 --t 12
"""
import argparse
import pathlib
import subprocess
import sys
import tempfile
import tomllib

from PIL import Image, ImageDraw, ImageFilter, ImageFont

RAIZ = pathlib.Path(__file__).resolve().parent.parent
FONTES = pathlib.Path("/usr/share/fonts/opentype/inter")
SAIDA = RAIZ / "out" / "marca"


def tokens() -> dict:
    with (RAIZ / "marca" / "tokens.toml").open("rb") as f:
        return tomllib.load(f)


def fonte(nome: str, tam: int) -> ImageFont.FreeTypeFont:
    """Aceita um nome dentro de FONTES ou um caminho absoluto."""
    caminho = pathlib.Path(nome) if nome.startswith("/") else FONTES / nome
    if not caminho.exists():
        sys.exit(f"fonte não encontrada: {caminho}")
    return ImageFont.truetype(str(caminho), tam)


# A Charter é Type1 (.pfb) e o Pillow a carrega — conferido. Ela carrega a
# marca e os títulos porque é do mesmo mundo do guia escrito; a Inter fica no
# que é pequeno, em movimento ou sobre imagem, onde a serifa perde.
CHARTER_BOLD = "/usr/share/fonts/X11/Type1/c0632bt_.pfb"
CHARTER = "/usr/share/fonts/X11/Type1/c0648bt_.pfb"
CHARTER_IT = "/usr/share/fonts/X11/Type1/c0649bt_.pfb"
BOLD = "Inter-Bold.otf"
MEDIO = "Inter-Medium.otf" if (FONTES / "Inter-Medium.otf").exists() else "Inter-Regular.otf"
SEMI = "Inter-SemiBold.otf"


def larg(d: ImageDraw.ImageDraw, txt: str, f) -> int:
    return int(d.textlength(txt, font=f))


def quebra(d, txt, f, limite):
    """Quebra o título na largura disponível, sem cortar palavra."""
    palavras, linhas, atual = txt.split(), [], ""
    for p in palavras:
        teste = f"{atual} {p}".strip()
        if larg(d, teste, f) <= limite or not atual:
            atual = teste
        else:
            linhas.append(atual)
            atual = p
    if atual:
        linhas.append(atual)
    return linhas


def frame_do_video(video: str, t: float, destino: str):
    """-copyts não é preciso aqui (não há filtro ass), mas o seek exato sim."""
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-ss", f"{t:.3f}",
                    "-i", video, "-frames:v", "1", destino], check=True)


def cobre(img: Image.Image, larg_alvo: int, alt_alvo: int) -> Image.Image:
    """Redimensiona cobrindo a área toda e corta o excedente, sem distorcer."""
    e = max(larg_alvo / img.width, alt_alvo / img.height)
    nova = img.resize((round(img.width * e), round(img.height * e)), Image.LANCZOS)
    x = (nova.width - larg_alvo) // 2
    y = (nova.height - alt_alvo) // 2
    return nova.crop((x, y, x + larg_alvo, y + alt_alvo))


def veu(img: Image.Image, cor: str, lados: str, forca: float = 0.92,
        plano_ate: float = 0.0, fim: float = 1.0):
    """Gradiente para o texto ter onde pousar.

    Sem isso o título disputa com a imagem e perde: o material tem 10% dos
    pixels acima de 200 de luminância. O véu é o que garante o contraste sem
    apagar a foto — a mesma função que o contorno cumpre na legenda.

    `plano_ate` mantém a opacidade cheia até essa fração, e só então começa a
    rampa, que zera em `fim`. Isso existe porque a primeira versão usava rampa
    desde a borda: no 1280 o véu morria em x=794 e o texto ia até x=825, então
    o final de cada linha caía fora dele. Medido, 24% dos pixels de texto da
    thumbnail ficavam abaixo do limiar de legibilidade — sempre no fim das
    linhas, que é justamente onde o violão claro aparece.

    A regra que sobra: o véu tem de cobrir a caixa de texto inteira com folga,
    não a metade dela.
    """
    w, h = img.size
    grad = Image.new("L", (w, h), 0)
    px = grad.load()
    if lados == "baixo":
        for y in range(h):
            if y <= h * plano_ate:
                v = 0.0
            else:
                v = min(1.0, (y - h * plano_ate) / max(1e-6, h * (fim - plano_ate)))
            col = int(255 * forca * v ** 1.4)
            for x in range(w):
                px[x, y] = col
    elif lados == "esquerda":
        for x in range(w):
            if x <= w * plano_ate:
                v = 1.0
            else:
                v = max(0.0, 1 - (x - w * plano_ate) / max(1e-6, w * (fim - plano_ate)))
            col = int(255 * forca * v ** 1.1)
            for y in range(h):
                px[x, y] = col
    camada = Image.new("RGB", (w, h), cor)
    return Image.composite(camada, img, grad)


def com_sombra(img, desenhos, raio=26, forca=0.93, cor="#000000"):
    """Escurece só o que está ATRÁS do texto, com um halo difuso.

    É a mesma ideia do contorno da legenda, em versão suave: em vez de escurecer
    uma faixa inteira do quadro, escurece a vizinhança das letras. A diferença
    é de design, não de medida — um véu forte o bastante para garantir contraste
    sozinho apaga a foto, e thumbnail sem imagem não é thumbnail. Com o halo, o
    véu pode ser leve e a foto continua viva.

    `desenhos` é a lista de (posição, texto, fonte) que será pintada depois.
    """
    m = Image.new("L", img.size, 0)
    dm = ImageDraw.Draw(m)
    for xy, txt, f in desenhos:
        dm.text(xy, txt, font=f, fill=255)
    m = m.filter(ImageFilter.GaussianBlur(raio))
    m = m.point(lambda v: int(v * forca))
    return Image.composite(Image.new("RGB", img.size, cor), img, m)


# ---------------------------------------------------------------------------
# Logos
# ---------------------------------------------------------------------------

def logo_lockup(t, w=1200, h=400, claro=False):
    """Assinatura horizontal. Serifada e em caixa mista, como o guia escrito.

    Caixa alta em serifa perde o que a serifa tem de bom — as ascendentes e o
    ritmo desigual das minúsculas. O material do guia usa caixa mista nos
    títulos e reserva a caixa alta com tracking para as etiquetas; o lockup
    segue a mesma regra.
    """
    p = t["paleta"]
    m = t["marca"]
    ground = p["papel"] if claro else p["fundo"]
    tinta = p["texto_tinta"] if claro else p["texto"]
    acento = p["acento"] if claro else p["acento_claro"]
    fraco = "#7A6E60" if claro else p["texto_fraco"]

    img = Image.new("RGB", (w, h), ground)
    d = ImageDraw.Draw(img)
    barra_w, gap, x0 = 14, 40, 90
    nome, suf = m["nome"], m["sufixo"]

    tam = 104
    while tam > 40:
        f_nome = fonte(CHARTER_BOLD, tam)
        usado = (x0 + barra_w + gap + larg(d, nome, f_nome) + 22
                 + larg(d, suf, f_nome) + x0)
        if usado <= w:
            break
        tam -= 4
    f_tema = fonte(MEDIO, max(19, int(tam * 0.26)))

    d.rectangle([x0, h // 2 - int(tam * 0.82), x0 + barra_w, h // 2 + int(tam * 0.62)],
                fill=acento)
    x = x0 + barra_w + gap
    topo = h // 2 - int(tam * 0.86)
    d.text((x, topo), nome, font=f_nome, fill=tinta)
    d.text((x + larg(d, nome, f_nome) + 22, topo), suf, font=f_nome, fill=acento)

    # etiqueta em caixa alta com tracking, como as do guia
    y_tema = topo + int(tam * 1.22)
    xx = x + 3
    for ch in m["tema"].upper():
        d.text((xx, y_tema), ch, font=f_tema, fill=fraco)
        xx += larg(d, ch, f_tema) + 3
    return img


def logo_monograma(t, lado=600):
    """Marca compacta: quadrado com PC. Para avatar e favicon."""
    p = t["paleta"]
    img = Image.new("RGB", (lado, lado), p["fundo"])
    d = ImageDraw.Draw(img)
    f = fonte(CHARTER_BOLD, int(lado * 0.46))
    txt = "PC"
    tw = larg(d, txt, f)
    cx = (lado - tw) // 2
    d.text((cx, lado * 0.22), txt, font=f, fill=p["texto"])
    # barra de acento embaixo, o mesmo elemento do lockup e da thumbnail
    bw = int(lado * 0.34)
    d.rectangle([(lado - bw) // 2, int(lado * 0.76),
                 (lado + bw) // 2, int(lado * 0.79)], fill=p["acento_claro"])
    return img


def logo_resolucao(t, lado=600):
    """V ▶ I — o gesto da harmonia funcional e o botão de play no mesmo sinal.

    O triângulo lê como play para quem passa e como resolução V→I para quem é
    músico. É o único dos três que diz do que o canal trata.
    """
    p = t["paleta"]
    img = Image.new("RGB", (lado, lado), p["fundo"])
    d = ImageDraw.Draw(img)
    f = fonte(CHARTER_BOLD, int(lado * 0.32))
    cy = lado // 2
    tri_w = int(lado * 0.13)
    gap = int(lado * 0.055)

    lv, li = larg(d, "V", f), larg(d, "I", f)
    total = lv + gap + tri_w + gap + li
    x = (lado - total) // 2
    topo = cy - int(lado * 0.32) // 2 - int(lado * 0.055)

    d.text((x, topo), "V", font=f, fill=p["texto"])
    x += lv + gap
    th = int(lado * 0.15)
    d.polygon([(x, cy - th // 2), (x + tri_w, cy), (x, cy + th // 2)],
              fill=p["acento_claro"])
    x += tri_w + gap
    d.text((x, topo), "I", font=f, fill=p["texto"])
    return img


# ---------------------------------------------------------------------------
# Peças com imagem
# ---------------------------------------------------------------------------

def thumbnail(t, video, tempo, titulo, sub, ep, w=1280, h=720, sem_texto=False):
    p = t["paleta"]
    m = t["marca"]
    with tempfile.TemporaryDirectory() as dtmp:
        f = f"{dtmp}/f.png"
        frame_do_video(video, tempo, f)
        img = cobre(Image.open(f).convert("RGB"), w, h)
    # véu leve: dá um clima e rebaixa a esquerda sem matar a foto
    img = veu(img, p["fundo"], "esquerda", 0.62, plano_ate=0.14, fim=0.78)

    x0, barra_w = 64, 12
    limite = int(w * 0.52)
    d = ImageDraw.Draw(img)

    # caixa mista: a serifa vive das minúsculas
    f_tit = fonte(CHARTER_BOLD, 84)
    linhas = quebra(d, titulo, f_tit, limite)
    while len(linhas) > 3 and f_tit.size > 50:
        f_tit = fonte(CHARTER_BOLD, f_tit.size - 6)
        linhas = quebra(d, titulo, f_tit, limite)
    f_sub = fonte(SEMI, 31)
    f_ep = fonte(BOLD, 26)
    f_ass = fonte(BOLD, 26)
    linhas_sub = quebra(d, sub, f_sub, limite) if sub else []

    alt = len(linhas) * int(f_tit.size * 1.10) + (56 if ep is not None else 0) \
        + (len(linhas_sub) * 42 + 12 if linhas_sub else 0)
    y = (h - alt) // 2
    y_topo = y

    # O "EP 03" não pode ser turquesa sobre a foto. O acento tem luminância
    # 0,51 — quase a do branco — e sobre um frame de tom médio dá 2,9:1, abaixo
    # do limiar. Medido: 795 dos 1855 pixels ruins da thumbnail eram só ele.
    # Vira um chip: o turquesa passa a ser FUNDO e o texto fica escuro, o que
    # garante o contraste e ainda destaca mais.
    desenhos = []
    yy = y
    chip = None
    if ep is not None:
        chip = (x0 + barra_w + 32, yy)
        yy += 58
    for l in linhas:
        desenhos.append(((x0 + barra_w + 32, yy), l, f_tit))
        yy += int(f_tit.size * 1.10)
    if linhas_sub:
        yy += 12
        for l in linhas_sub:
            desenhos.append(((x0 + barra_w + 32, yy), l, f_sub))
            yy += 42
    nome = f"{m['nome']} {m['sufixo']}"
    desenhos.append(((x0 + barra_w + 32, h - 62), nome, f_ass))

    img = com_sombra(img, desenhos)
    d = ImageDraw.Draw(img)
    if chip is not None:
        cx, cy = chip
        tw = larg(d, f"EP {ep:02d}", f_ep)
        d.rectangle([cx - 14, cy - 8, cx + tw + 16, cy + f_ep.size + 14],
                    fill=p["acento"])
    if sem_texto:
        return img

    d.rectangle([x0, y_topo, x0 + barra_w, yy - 30], fill=p["acento_claro"])
    if chip is not None:
        # texto CREME sobre o chip: o terracota é escuro (luminância 0,146),
        # então ele é o fundo e o texto claro por cima dá 4,8:1. Com o turquesa
        # era o contrário — ele é claro e pedia texto escuro.
        d.text(chip, f"EP {ep:02d}", font=f_ep, fill=p["texto"])
    # Sobre foto, TUDO em creme. A hierarquia vem do tamanho e do peso, não da
    # cor: o acento terracota mede 3,4:1 sobre escuro e o cinza fraco 2,1:1
    # sobre tom médio. Os dois continuam valendo nas peças de fundo sólido.
    #
    # E um contorno fino, pelo mesmo motivo que a legenda tem um: a Charter é
    # serifada e modulada, e são os traços finos que somem primeiro sobre foto.
    # Só o halo não resolveu — com ele sozinho a thumbnail media 12% a 15% de
    # pixels ilegíveis contra 0% a 2% da versão sem serifa. O contorno devolve
    # massa ao traço fino e é o que torna a serifa viável aqui.
    for xy, txt, f in desenhos:
        d.text(xy, txt, font=f, fill=p["texto"],
               stroke_width=2, stroke_fill=p["fundo"])
    return img


def post_feed(t, video, tempo, titulo, sub, w=1080, h=1350, sem_texto=False):
    """Post de feed em PAPEL, não no escuro.

    É onde a direção editorial do guia cabe inteira: foto em cima, tipografia
    serifada sobre creme embaixo. E resolve um problema de contraste de graça —
    sobre fundo claro o terracota é texto legível (5,0:1), o que no escuro ele
    não é (3,4:1). Cada ground usa o acento que serve a ele.
    """
    p = t["paleta"]
    m = t["marca"]
    img = Image.new("RGB", (w, h), p["papel"])
    with tempfile.TemporaryDirectory() as dtmp:
        f = f"{dtmp}/f.png"
        frame_do_video(video, tempo, f)
        foto = cobre(Image.open(f).convert("RGB"), w, int(h * 0.58))
    img.paste(foto, (0, 0))
    d = ImageDraw.Draw(img)

    y = int(h * 0.58)
    d.rectangle([0, y, w, y + 7], fill=p["acento"])
    if sem_texto:
        return img

    x0, limite = 76, w - 152
    y += 62

    # etiqueta em caixa alta com tracking, como as do guia
    f_et = fonte(BOLD, 22)
    xx = x0
    for ch in m["tema"].upper():
        d.text((xx, y), ch, font=f_et, fill=p["acento"])
        xx += larg(d, ch, f_et) + 3
    y += 46

    f_tit = fonte(CHARTER_BOLD, 78)
    linhas = quebra(d, titulo, f_tit, limite)
    while len(linhas) > 3 and f_tit.size > 48:
        f_tit = fonte(CHARTER_BOLD, f_tit.size - 5)
        linhas = quebra(d, titulo, f_tit, limite)
    for l in linhas:
        d.text((x0, y), l, font=f_tit, fill=p["texto_tinta"])
        y += int(f_tit.size * 1.14)

    if sub:
        y += 20
        f_sub = fonte(CHARTER, 38)
        for l in quebra(d, sub, f_sub, limite):
            d.text((x0, y), l, font=f_sub, fill="#6B6055")
            y += 50

    d.line([(x0, h - 118), (w - x0, h - 118)], fill="#DDD5CB", width=1)
    f_h = fonte(BOLD, 27)
    d.text((x0, h - 92), f"{m['nome']} {m['sufixo']}", font=f_h, fill=p["texto_tinta"])
    hw = larg(d, m["handle"], f_h)
    d.text((w - x0 - hw, h - 92), m["handle"], font=f_h, fill="#6B6055")
    return img


def story(t, video, tempo, titulo, w=1080, h=1920, sem_texto=False):
    """Capa de story/Reels. Respeita a mesma safe area da legenda."""
    p = t["paleta"]
    m = t["marca"]
    fm = t["formato"]["9x16"]
    with tempfile.TemporaryDirectory() as dtmp:
        f = f"{dtmp}/f.png"
        frame_do_video(video, tempo, f)
        img = cobre(Image.open(f).convert("RGB"), w, h)
    img = veu(img, p["fundo"], "baixo", 0.72, plano_ate=0.34, fim=0.74)
    if sem_texto:
        return img
    d = ImageDraw.Draw(img)

    # o título pousa logo acima da faixa que a interface cobre
    base = h - fm["margem_inferior"] - 40
    x0, limite = 72, w - 144
    f_tit = fonte(CHARTER_BOLD, 96)
    linhas = quebra(d, titulo, f_tit, limite)
    while len(linhas) > 4 and f_tit.size > 58:
        f_tit = fonte(CHARTER_BOLD, f_tit.size - 6)
        linhas = quebra(d, titulo, f_tit, limite)

    y = base - len(linhas) * int(f_tit.size * 1.1)
    d.rectangle([x0, y - 34, x0 + 96, y - 22], fill=p["acento_claro"])
    for l in linhas:
        d.text((x0, y), l, font=f_tit, fill=p["texto"])
        y += int(f_tit.size * 1.1)

    f_h = fonte(BOLD, 34)
    d.text((x0, h - fm["margem_inferior"] + 24),
           f"{m['nome']} {m['sufixo']}", font=f_h, fill=p["texto"])
    return img


def svgs(t):
    """Versão vetorial dos logos, para levar ao Figma ou ao Illustrator.

    Vive aqui dentro, e não num script à parte, porque asset gerado fora do
    gerador diverge em silêncio: a primeira leva de SVGs foi escrita à mão e
    continuou turquesa depois que a paleta inteira virou terracota — arquivo
    certo no nome, cor errada no conteúdo, sem nada acusando.
    """
    p, m = t["paleta"], t["marca"]
    aviso = ("<!-- Texto em Bitstream Charter. Para usar fora desta máquina,\n"
             "     converta em curvas (Figma: Outline Stroke; Illustrator:\n"
             "     Criar Contornos). Cores de marca/tokens.toml. -->")
    serif = "Charter, 'Charis SIL', Georgia, serif"

    pecas = {
        "logo-resolucao.svg": f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 600" width="600" height="600">
{aviso}
  <rect width="600" height="600" fill="{p['fundo']}"/>
  <text x="196" y="352" font-family="{serif}" font-weight="700"
        font-size="192" fill="{p['texto']}" text-anchor="middle">V</text>
  <polygon points="268,258 348,300 268,342" fill="{p['acento_claro']}"/>
  <text x="410" y="352" font-family="{serif}" font-weight="700"
        font-size="192" fill="{p['texto']}" text-anchor="middle">I</text>
</svg>''',
        "logo-monograma.svg": f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 600" width="600" height="600">
{aviso}
  <rect width="600" height="600" fill="{p['fundo']}"/>
  <text x="300" y="392" font-family="{serif}" font-weight="700"
        font-size="276" fill="{p['texto']}" text-anchor="middle">PC</text>
  <rect x="198" y="456" width="204" height="18" fill="{p['acento_claro']}"/>
</svg>''',
        "logo-lockup.svg": f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 400" width="1200" height="400">
{aviso}
  <rect width="1200" height="400" fill="{p['fundo']}"/>
  <rect x="90" y="114" width="14" height="150" fill="{p['acento_claro']}"/>
  <text x="144" y="222" font-family="{serif}" font-weight="700"
        font-size="98" fill="{p['texto']}">{m['nome']}</text>
  <text x="806" y="222" font-family="{serif}" font-weight="700"
        font-size="98" fill="{p['acento_claro']}">{m['sufixo']}</text>
  <text x="148" y="286" font-family="Inter, sans-serif" font-weight="500"
        font-size="27" letter-spacing="3" fill="{p['texto_fraco']}">{m['tema'].upper()}</text>
</svg>''',
    }
    for nome, conteudo in pecas.items():
        (SAIDA / nome).write_text(conteudo, encoding="utf-8")
        print(f"  out/marca/{nome}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("peca", choices=["logos", "thumb", "post", "story", "tudo"])
    ap.add_argument("video", nargs="?")
    ap.add_argument("--t", type=float, default=12.0)
    ap.add_argument("--titulo", default="Dominante secundária")
    ap.add_argument("--sub", default="o acorde que puxa para onde você não espera")
    ap.add_argument("--ep", type=int, default=3)
    args = ap.parse_args()

    t = tokens()
    SAIDA.mkdir(parents=True, exist_ok=True)

    def salva(img, nome):
        caminho = SAIDA / nome
        img.save(caminho)
        print(f"  {caminho.relative_to(RAIZ)}  {img.width}x{img.height}")

    if args.peca in ("logos", "tudo"):
        print("logos:")
        salva(logo_lockup(t), "logo-lockup.png")
        salva(logo_monograma(t), "logo-monograma.png")
        salva(logo_resolucao(t), "logo-resolucao.png")
        salva(logo_lockup(t, claro=True), "logo-lockup-claro.png")
        svgs(t)

    if args.peca in ("thumb", "post", "story", "tudo"):
        if not args.video:
            sys.exit("estas peças precisam de um vídeo de onde tirar o frame")
        print("peças com imagem:")
        if args.peca in ("thumb", "tudo"):
            salva(thumbnail(t, args.video, args.t, args.titulo, args.sub,
                            args.ep), "thumbnail.png")
        if args.peca in ("post", "tudo"):
            salva(post_feed(t, args.video, args.t, args.titulo, args.sub),
                  "post-feed.png")
        if args.peca in ("story", "tudo"):
            salva(story(t, args.video, args.t, args.titulo), "story.png")


if __name__ == "__main__":
    main()
