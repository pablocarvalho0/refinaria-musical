#!/usr/bin/env python3
"""As cartelas do improviso_4, em três variantes, para escolher na tela.

Por que um arquivo separado do cartelas.py: aquele desenha a peça de COVER —
obra, autoria, ano, e um único executante. Aqui a peça é outra: não há obra
de terceiro para creditar, há uma piada para contar e DUAS pessoas tocando.
O que se reusa dali é o desenho (barra, chip, scrim, ancoragem na safe area);
o que muda é a composição. Nada de cor, tamanho ou margem é escrito aqui:
tudo continua vindo de marca/tokens.toml.

As três variantes mudam UMA coisa cada, para a escolha ser sobre uma pergunta
e não sobre um pacote:

  1  bloco    a anatomia da casa, igual à do improviso_3_cover. A piada cabe
              inteira numa cartela só, discreta, no rodapé.
  2  batidas  a mesma anatomia, mas a piada em DUAS cartelas: setup, e depois
              a punchline sozinha. É tempo cômico — o texto troca enquanto a
              imagem corre, que é o que segura o olho num Reel.
  3  placa    cartela de tela cheia, fundo sólido, tipo abertura de filme. A
              imagem só entra depois da piada, e o fim é uma placa de créditos.

Uso:
    python scripts/cartelas_improviso.py --variante 2 \
        --duracao 45.40 --prefixo work/improviso_4_v.v2

    # em 4K, com a abertura segurada até o tempo forte em que o Rafael entra
    python scripts/cartelas_improviso.py --variante 1 --largura 2160 \
        --abertura-ate 9.706 --duracao 45.43 --prefixo work/improviso_4_4k

Imprime, uma por linha, as especificações `PNG:entra:sai` na ordem, prontas
para o scripts/monta-cartelas.sh.
"""
import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from PIL import Image

from cartelas import (_chip, _espaco, _fio, _pinta, _texto, _tracking,
                      faces, fonte, monta, tokens)

FMT = "9x16"

# ---------------------------------------------------------------------------
# O texto do episódio. Fica aqui em cima, junto, porque é o que muda de um
# episódio para o outro — e porque ler as três variantes lado a lado é a
# única forma de perceber que uma delas diz a piada duas vezes.
# ---------------------------------------------------------------------------
ROTULO = "improviso"
PIADA = ["Eis que você pluga", "o violão no amp", "com distorção"]
SETUP = ["Um violão.", "Um amp de guitarra."]
PUNCH = "Distorção."
PARCEIRO = "com Rafael na bateria"
FICHA = [("violão distorcido", "Pablo Carvalho"),
         ("bateria", "Rafael Alves")]


# ---------------------------------------------------------------------------
# Placa de tela cheia
#
# Mesma anatomia do bloco — barra de acento, chip, texto —, mas sobre fundo
# sólido e centrada na parte VISÍVEL do quadro, não no quadro inteiro: os
# 480 px de baixo são a safe area que a interface do Reels cobre, e centrar
# no meio geométrico jogaria o bloco para trás dos botões.
# ---------------------------------------------------------------------------

def placa(t, elementos, sem_texto=False):
    p, f = t["paleta"], t["formato"][FMT]
    w, h = f["largura"], f["altura"]
    util = h - f["margem_inferior"]

    provisorio = 400
    prova = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    _pinta(prova, t, FMT, elementos, provisorio, sem_texto=False)
    caixa = prova.getbbox()
    if caixa is None:
        raise SystemExit("a placa saiu vazia")
    _, topo, _, fundo = caixa
    y0 = provisorio + (util - (fundo - topo)) // 2 - topo

    img = Image.new("RGBA", (w, h), p["fundo"])
    _pinta(img, t, FMT, elementos, y0, sem_texto)
    return img


# ---------------------------------------------------------------------------
# Os blocos de texto, montados uma vez e reusados pelas três variantes
# ---------------------------------------------------------------------------

def bloco_piada(t, linhas, com_chip=True, destaque=False, rodape=None):
    c, ca, fc = t["cartela"], t["cartela"]["abertura"], faces(t)
    el = c["entrelinha"]
    # a punchline sozinha ganha corpo: é uma palavra só, e uma palavra só no
    # tamanho de três linhas não lê como título, lê como sussurro.
    tam = int(ca["tamanho_titulo"] * 1.5) if destaque else ca["tamanho_titulo"]
    f_tit = fonte(fc["serif_bold"], tam)
    f_cred = fonte(fc["serif_it"], ca["tamanho_credito"])
    f_chip = fonte(fc["sans_bold"], ca["tamanho_chip"])

    el_ = []
    if com_chip:
        el_.append(_chip(ROTULO.upper(), f_chip, ca["chip_tracking"],
                         int(f_chip.size * 2.2)))
    el_ += [_texto(linha, f_tit, int(f_tit.size * el)) for linha in linhas]
    if rodape:
        el_ += [_espaco(int(f_cred.size * 0.34)),
                _texto(rodape, f_cred, int(f_cred.size * el))]
    return el_


def bloco_ficha(t):
    """Quem tocou o quê, e o handle embaixo do fio.

    A etiqueta vem ANTES do nome, em caixa alta e pequena. É a ordem de uma
    ficha técnica, e ela resolve sozinha o problema de quem lê rápido: o olho
    encontra 'bateria' e já sabe que o nome ao lado é do baterista, sem ter de
    inferir pela ordem. Num crédito de duas pessoas isso não é decoração.
    """
    c, cc, m, fc = t["cartela"], t["cartela"]["creditos"], t["marca"], faces(t)
    el = c["entrelinha"]
    f_et = fonte(fc["sans_bold"], cc["tamanho_etiqueta"])
    f_nome = fonte(fc["serif_bold"], cc["tamanho_nome"])
    f_handle = fonte(fc["sans_medio"], cc["tamanho_handle"])

    el_ = []
    for i, (papel, nome) in enumerate(FICHA):
        if i:
            el_.append(_espaco(int(f_nome.size * 0.34)))
        el_.append(_tracking(papel.upper(), f_et, cc["etiqueta_tracking"],
                             int(f_et.size * 1.7)))
        el_.append(_texto(nome, f_nome, int(f_nome.size * el)))
    el_ += [_espaco(int(f_nome.size * 0.42)),
            _fio(cc["fio_largura"], int(f_handle.size * 1.5),
                 int(f_nome.size * 3.4)),
            _texto(m["handle"], f_handle, int(f_handle.size * el))]
    return el_


# ---------------------------------------------------------------------------
# As três variantes: cada uma devolve [(sufixo, desenhador, t0, t1)]
# ---------------------------------------------------------------------------

def plano(t, variante, dur, abertura_ate=None):
    """As cartelas de uma variante, como [(sufixo, desenhador, t0, t1)].

    `abertura_ate` segura a cartela de abertura até esse instante em vez de
    usar a duração do token. É o "reveal": no improviso_4 ela fica até
    9,706s, que é quando o Rafael aparece — a piada e a entrada dele viram
    um evento só. O instante quer cair num tempo forte; quem mede é
    scripts/grade-musical.py --encaixa.
    """
    c = t["cartela"]
    ab, cr = c["abertura"], c["creditos"]
    t0 = ab["atraso"]
    fim_cred = dur
    fim_ab = abertura_ate if abertura_ate is not None else t0 + ab["duracao"]

    if variante == 1:
        el_ab = bloco_piada(t, PIADA, rodape=PARCEIRO)
        return [
            ("abertura", lambda st: monta(t, FMT, el_ab, st), t0, fim_ab),
            ("creditos", lambda st: monta(t, FMT, bloco_ficha(t), st),
             dur - cr["duracao"], fim_cred),
        ]

    if variante == 2:
        # o setup sai e a punchline entra no mesmo lugar: a troca é o efeito.
        # Sem sobreposição — 0,1s de respiro entre as duas, senão os dois
        # fades se cruzam e por um instante lê-se as duas ao mesmo tempo.
        meio = t0 + ab["duracao"] * 0.48
        el_s = bloco_piada(t, SETUP)
        el_p = bloco_piada(t, [PUNCH], com_chip=False, destaque=True,
                           rodape=PARCEIRO)
        return [
            ("setup", lambda st: monta(t, FMT, el_s, st), t0, meio),
            ("punch", lambda st: monta(t, FMT, el_p, st),
             meio + 0.10,
             fim_ab if abertura_ate is not None else t0 + ab["duracao"] * 1.15),
            ("creditos", lambda st: monta(t, FMT, bloco_ficha(t), st),
             dur - cr["duracao"], fim_cred),
        ]

    if variante == 3:
        # a placa é opaca: enquanto ela está em tela não há imagem. Por isso
        # ela é curta e entra em t=0 — o primeiro frame de um Reel é a capa,
        # e uma placa que demora a sair custa retenção.
        el_ab = bloco_piada(t, PIADA, rodape=PARCEIRO)
        return [
            ("placa-abertura", lambda st: placa(t, el_ab, st),
             0.0, abertura_ate if abertura_ate is not None else 3.20),
            ("placa-creditos", lambda st: placa(t, bloco_ficha(t), st),
             dur - 5.00, fim_cred),
        ]

    raise SystemExit(f"variante desconhecida: {variante}")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--variante", type=int, required=True, choices=(1, 2, 3))
    ap.add_argument("--duracao", type=float, required=True,
                    help="duração do vídeo em segundos")
    ap.add_argument("--prefixo", required=True)
    ap.add_argument("--largura", type=int, default=None,
                    help="largura do vídeo em px; escala os tokens. "
                         "Omitido, usa a do formato (1080). Ver 'Resolução "
                         "de entrega' no CLAUDE.md")
    ap.add_argument("--abertura-ate", type=float, default=None,
                    metavar="SEG",
                    help="segura a cartela de abertura até este instante "
                         "(o 'reveal'), em vez da duração do token")
    args = ap.parse_args()

    t = tokens(args.largura)
    pref = pathlib.Path(args.prefixo)
    pref.parent.mkdir(parents=True, exist_ok=True)

    specs = []
    for sufixo, desenha, t0, t1 in plano(t, args.variante, args.duracao,
                                        args.abertura_ate):
        for sem_texto in (False, True):
            nome = f"{pref}.{sufixo}{'.sem-texto' if sem_texto else ''}.png"
            img = desenha(sem_texto)
            img.save(nome)
            if not sem_texto:
                print(f"  {nome}  {img.width}x{img.height}", file=sys.stderr)
                specs.append(f"{nome}:{t0:.2f}:{t1:.2f}")
    print("\n".join(specs))


if __name__ == "__main__":
    main()
