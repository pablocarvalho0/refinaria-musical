#!/usr/bin/env python3
"""
Monta legendas (.srt e .ass) a partir do sidecar de palavras do Whisper.

Os segmentos que o Whisper devolve não servem como legenda: no ep00 o
primeiro tem 29,00s e 427 caracteres. O que serve é o alinhamento por
palavra (`transcreve.sh --word-timestamps`), reagrupado aqui por regras
de leitura explícitas.

Uso: python scripts/legenda.py work/ep00.words.tsv \
         --segmentos out/ep00/ep00.segmentos.txt
"""
import argparse
import pathlib
import re
import sys
import tomllib

import sys as _sys
_sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from projeto import pasta_episodio, resumo as resumo_projeto

# Regras de leitura. Os números seguem a prática de legendagem para vídeo
# (BBC/Netflix convergem nesta faixa): duas linhas de no máximo ~42
# caracteres, entre 1 e 6 segundos na tela. Ficam aqui em cima porque são
# o que se ajusta depois de ver o resultado na tela.
#
# Estes números são de LEITURA, não de formato, e por isso não estão em
# marca/tokens.toml. São iguais no horizontal e no vertical de propósito: o
# texto e os tempos dos cues não podem mudar entre formatos, senão um corte
# vertical tirado do longo teria legenda diferente do longo. O que muda entre
# formatos é só a apresentação — tamanho, margem, PlayRes —, e essa parte sim
# vem dos tokens. No 16:9 o limite de 42 caracteres nem chega a ser espacial:
# a área útil comporta 73.
MAX_CHARS_LINHA = 42
MAX_LINHAS = 2
MAX_CHARS_CUE = MAX_CHARS_LINHA * MAX_LINHAS
MIN_DUR = 1.20          # nenhum cue pisca
MAX_DUR = 5.00          # nenhum cue estaciona
GAP_QUEBRA = 0.70       # pausa entre palavras que fecha o cue
FOLGA_FIM = 0.20        # respiro depois da última palavra
GAP_MINIMO = 0.08       # espaço entre cues, para o corte ser visível
MAX_CPS = 17.0          # velocidade de leitura confortável, char/s
MIN_PALAVRA_NO_CORTE = 0.50   # fração audível para a palavra entrar na legenda

FORTE = ".!?…"          # pontuação que sempre fecha o cue
FRACA = ",;:"           # fecha só se o cue já está razoavelmente cheio
CHEIO = 0.60            # "razoavelmente cheio" = 60% do teto


def parse_hms(t: str) -> float:
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def le_regioes_fala(caminho: pathlib.Path) -> list[tuple[float, float]]:
    """Extrai as regiões FALA do segmentos.txt do segmenta.py."""
    regioes = []
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        if linha.startswith("#") or not linha.strip():
            continue
        campos = linha.split("\t")
        if len(campos) >= 3 and campos[0].strip() == "FALA":
            regioes.append((parse_hms(campos[1]), parse_hms(campos[2])))
    return regioes


def dentro_da_fala(ini: float, fim: float,
                   regioes: list[tuple[float, float]]) -> bool:
    """Sobreposição com alguma região FALA.

    Rede de segurança: o Whisper alucina texto sobre violão solo, e no
    ep00 152 dos 189 segundos são música. Sem regiões carregadas, não
    filtra nada.
    """
    if not regioes:
        return True
    return any(ini < r_fim and fim > r_ini for r_ini, r_fim in regioes)


PONTUACAO = ".,!?;:…\"'()[]"


def normaliza(t: str) -> str:
    return t.strip(PONTUACAO).lower()


def le_glossario(caminho: pathlib.Path) -> list[tuple[list[str], str, str]]:
    """Regras errado -> certo, com o lado errado já tokenizado."""
    regras = []
    if not caminho.exists():
        return regras
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        if linha.startswith("#") or not linha.strip():
            continue
        campos = linha.split("\t")
        if len(campos) < 2:
            continue
        errado, certo = campos[0].strip(), campos[1].strip()
        nota = campos[2].strip() if len(campos) > 2 else ""
        regras.append(([normaliza(x) for x in errado.split()], certo, nota))
    # Regra mais longa primeiro: "Falta nada do YouTube" tem que vencer
    # "Falta nada" se um dia as duas existirem.
    regras.sort(key=lambda r: -len(r[0]))
    return regras


def aplica_glossario(palavras: list[dict],
                     regras: list[tuple[list[str], str, str]]) -> tuple[list[dict], list[dict]]:
    """Substitui sequências conhecidas, redistribuindo os timestamps.

    O trecho corrigido ocupa exatamente a janela de tempo do trecho
    original; dentro dela cada palavra nova recebe uma fatia proporcional
    ao seu comprimento. Não é alinhamento de verdade, mas o erro fica
    dentro de um cue e nunca desloca a legenda.
    """
    if not regras:
        return palavras, []
    saida, trocas, i = [], [], 0
    while i < len(palavras):
        casou = False
        for tokens, certo, nota in regras:
            n = len(tokens)
            if i + n > len(palavras):
                continue
            janela = [normaliza(p["txt"]) for p in palavras[i:i + n]]
            if janela != tokens:
                continue

            orig = palavras[i:i + n]
            ini, fim = orig[0]["ini"], orig[-1]["fim"]
            novas_txt = certo.split()

            # Preserva a pontuação final do original ("YouTube," ->
            # "YouTube,") quando a correção não traz a sua.
            cauda = orig[-1]["txt"][len(orig[-1]["txt"].rstrip(PONTUACAO)):]
            if cauda and not novas_txt[-1].endswith(tuple(PONTUACAO)):
                novas_txt[-1] += cauda

            total = sum(len(x) for x in novas_txt) or 1
            t = ini
            for x in novas_txt:
                dt = (fim - ini) * len(x) / total
                saida.append({"ini": t, "fim": t + dt, "txt": x,
                              "prob": 1.0, "corrigida": True})
                t += dt
            saida[-1]["fim"] = fim

            trocas.append({"ini": ini, "de": " ".join(p["txt"] for p in orig),
                           "para": " ".join(novas_txt), "nota": nota})
            i += n
            casou = True
            break
        if not casou:
            saida.append(palavras[i])
            i += 1
    return saida, trocas


def le_cortes(caminho: pathlib.Path) -> list[tuple[float, float]]:
    """Trechos a MANTER do cortes.txt, no mesmo formato que o corta.sh lê."""
    trechos = []
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        if linha.startswith("#") or not linha.strip():
            continue
        campos = linha.split()
        if len(campos) < 2:
            continue
        trechos.append((parse_hms(campos[0]), parse_hms(campos[1])))
    trechos.sort()
    return trechos


def sobra(p: dict, s_ini: float, s_fim: float) -> float:
    """Fração da palavra que o corte preserva.

    Palavra que só encosta no trecho vira fragmento inaudível: no
    improviso_2 o "aí" de 60,850–61,730 perde 93% de si para o corte
    que entra em 61,670, e entrava na legenda inteiro. Quem lê vê uma
    palavra que ninguém falou.
    """
    dur = p["fim"] - p["ini"]
    if dur <= 0:
        return 1.0 if s_ini <= p["ini"] < s_fim else 0.0
    return max(0.0, min(p["fim"], s_fim) - max(p["ini"], s_ini)) / dur


def remapeia_cortes(palavras: list[dict],
                    trechos: list[tuple[float, float]]) -> tuple[list[dict], int]:
    """Leva as palavras da timeline original para a do arquivo cortado.

    O corta.sh concatena os trechos mantidos, então tudo que vem depois de
    uma emenda anda para trás. Sem isso a legenda do arquivo cortado sai
    deslocada pela soma do que foi removido antes dela — no improviso_2,
    102s no último trecho.

    A última palavra de cada trecho recebe `corte_depois`, para o cue
    fechar na emenda: as palavras vizinhas passam a ficar a milissegundos
    uma da outra, e sem a marca o monta_cues juntaria num cue só duas
    falas que estavam a um minuto de distância.
    """
    saida, acumulado, mantidas = [], 0.0, 0
    for s_ini, s_fim in trechos:
        dentro = [p for p in palavras
                  if sobra(p, s_ini, s_fim) >= MIN_PALAVRA_NO_CORTE]
        for p in dentro:
            q = dict(p)
            # Clampa a palavra que encosta na fronteira. O corte é feito na
            # fronteira de palavra de propósito, então isto é folga de
            # milissegundos, não texto partido.
            q["ini"] = max(p["ini"], s_ini) - s_ini + acumulado
            q["fim"] = min(p["fim"], s_fim) - s_ini + acumulado
            saida.append(q)
        if dentro:
            saida[-1]["corte_depois"] = True
        mantidas += len(dentro)
        acumulado += s_fim - s_ini
    return saida, len(palavras) - mantidas


def le_palavras(caminho: pathlib.Path) -> list[dict]:
    palavras = []
    linhas = caminho.read_text(encoding="utf-8").splitlines()
    for linha in linhas[1:]:                      # pula o cabeçalho
        campos = linha.split("\t")
        if len(campos) < 3:
            continue
        palavras.append({
            "ini": float(campos[0]),
            "fim": float(campos[1]),
            "txt": campos[2],
            "prob": float(campos[3]) if len(campos) > 3 else 1.0,
        })
    return palavras


def monta_cues(palavras: list[dict],
               max_chars_cue: int = MAX_CHARS_CUE) -> list[dict]:
    """Agrupa palavras em cues. Fecha em pontuação, pausa ou teto."""
    cues, buf = [], []

    def texto(buf):
        return " ".join(p["txt"] for p in buf)

    for i, p in enumerate(palavras):
        buf.append(p)
        t = texto(buf)
        prox = palavras[i + 1] if i + 1 < len(palavras) else None

        fecha = False
        motivo = None
        if prox is None:
            fecha = True; motivo = "fim"
        elif t and t[-1] in FORTE:
            fecha = True; motivo = "ponto"
        elif t and t[-1] in FRACA and len(t) >= max_chars_cue * CHEIO:
            fecha = True; motivo = "virgula"
        elif prox["ini"] - p["fim"] > GAP_QUEBRA:
            fecha = True; motivo = "pausa"
        elif len(t) + 1 + len(prox["txt"]) > max_chars_cue:
            fecha = True; motivo = "TETO"
        elif prox["fim"] - buf[0]["ini"] > MAX_DUR:
            fecha = True; motivo = "durmax"
        elif p.get("corte_depois"):
            fecha = True

        if fecha:
            cues.append({"ini": buf[0]["ini"], "fim": buf[-1]["fim"],
                         "txt": t, "palavras": buf, "motivo": motivo,
                         "fim_trecho": bool(p.get("corte_depois")),
                         "prob_min": min(x["prob"] for x in buf)})
            buf = []
    return cues


# Palavras que não sustentam o fim de um cue: elas pedem o que vem depois.
# Terminar ali parte o sintagma no meio e o espectador lê "vou fazer uma" e
# só descobre "inveja" no cue seguinte — foi a queixa que originou a regra.
# Só preposição, artigo e conjunção: são fechadas e não dependem de análise.
# Verbo auxiliar ("vou", "quero") tentaria adivinhar demais e recuaria o cue
# a ponto de esvaziá-lo.
FUNCIONAIS = {
    "de", "do", "da", "dos", "das", "em", "no", "na", "nos", "nas",
    "ao", "aos", "à", "às", "para", "pra", "pro", "por", "pelo", "pela",
    "pelos", "pelas", "com", "sem", "sob", "sobre", "entre", "até",
    "desde", "após", "contra", "num", "numa", "dum", "duma",
    "o", "a", "os", "as", "um", "uma", "uns", "umas",
    "e", "ou", "mas", "que", "se", "como", "quando", "porque", "pois",
    "nem", "então", "qual", "quais", "cujo", "cuja", "meu", "minha",
    "seu", "sua", "nosso", "nossa", "este", "esta", "esse", "essa",
}


def nu(txt: str) -> str:
    """A palavra sem pontuação nem caixa, para consultar FUNCIONAIS."""
    return txt.strip(".,;:!?…\"'()").lower()


def ajusta_fronteiras(cues: list[dict], max_chars_cue: int) -> list[dict]:
    """Empurra para o cue seguinte a palavra funcional que ficou no fim.

    Só age onde o cue fechou por falta de espaço ('TETO' ou duração): fecho
    por pontuação ou por pausa já cai em fronteira boa, e mexer ali seria
    desfazer o que o texto mandou. A palavra só anda se couber do outro lado
    e se sobrar coisa deste — um cue não pode ficar vazio para embelezar o
    vizinho.
    """
    for i in range(len(cues) - 1):
        c, prox = cues[i], cues[i + 1]
        if c.get("motivo") not in ("TETO", "durmax"):
            continue
        while len(c["palavras"]) >= 2 and nu(c["palavras"][-1]["txt"]) in FUNCIONAIS:
            movida = c["palavras"][-1]
            if len(movida["txt"]) + 1 + len(prox["txt"]) > max_chars_cue:
                break
            c["palavras"].pop()
            prox["palavras"].insert(0, movida)
            for x in (c, prox):
                x["txt"] = " ".join(w["txt"] for w in x["palavras"])
                x["ini"] = x["palavras"][0]["ini"]
                x["fim"] = x["palavras"][-1]["fim"]
    return cues


def funde_orfaos(cues: list[dict], max_chars_cue: int = MAX_CHARS_CUE,
                 min_dur: float = MIN_DUR) -> list[dict]:
    """Junta ao anterior o cue curto demais que fecha numa emenda.

    Fora de uma emenda um cue curto tem para onde crescer: o ajusta_tempos
    empurra o fim até MIN_DUR. No fim de um trecho não tem — o próximo cue
    é outro momento do vídeo, e esticar poria o texto por cima do corte.
    Sem isto o improviso_2 termina o segundo trecho com "música" sozinho
    por 0,93s, abaixo do mínimo que este arquivo define para não piscar.

    Só funde o que cabe: o teto de caracteres é regra de leitura e continua
    valendo. O teto de duração cede, porque um cue longo é legível e um cue
    que pisca não é.
    """
    saida = []
    for c in cues:
        anterior = saida[-1] if saida else None
        orfao = (c["fim_trecho"] and c["fim"] - c["ini"] < min_dur
                 and anterior is not None and not anterior["fim_trecho"]
                 and len(anterior["txt"]) + 1 + len(c["txt"]) <= max_chars_cue)
        if orfao:
            anterior["txt"] += " " + c["txt"]
            anterior["fim"] = c["fim"]
            anterior["fim_trecho"] = True
            anterior["prob_min"] = min(anterior["prob_min"], c["prob_min"])
            continue
        saida.append(c)
    return saida


def ajusta_tempos(cues: list[dict], min_dur: float = MIN_DUR) -> list[dict]:
    """Dá folga no fim e garante min_dur, sem invadir o cue seguinte.

    O GAP_MINIMO sai do espaço que sobra entre um cue e o outro — nunca da
    palavra. Antes o limite era 'próximo início menos o gap' e entrava num
    min() com o fim da fala: quando as palavras vinham coladas, o cue era
    aparado para ANTES da última palavra terminar, e ela sumia da tela
    enquanto ainda estava sendo dita. O sintoma foi visto na tela antes de
    ser medido; medido depois no improviso_3 com cue curto, 7 dos 12 cues
    perdiam 80 ms — o valor exato do GAP_MINIMO. Com cue longo o defeito
    quase não aparece (1 de 5), porque há menos fronteiras para errar.
    """
    for i, c in enumerate(cues):
        fim_palavra = c["fim"]
        prox = (cues[i + 1]["ini"] if i + 1 < len(cues) else float("inf"))
        # piso: a palavra inteira, salvo quando o próximo cue já começou
        # (o alinhamento do Whisper encavala palavras de vez em quando).
        piso = min(fim_palavra, prox)
        limite = max(prox - GAP_MINIMO, piso)
        if c["fim_trecho"]:
            limite = min(limite, fim_palavra)
        c["fim"] = min(fim_palavra + FOLGA_FIM, limite)
        if c["fim"] - c["ini"] < min_dur:
            c["fim"] = max(c["fim"], min(c["ini"] + min_dur, limite))
        if c["fim"] <= c["ini"]:
            c["fim"] = c["ini"] + 0.30
    return cues


def estica_rapidos(cues: list[dict]) -> list[dict]:
    """Dá mais tempo de tela a quem está acima do limite de leitura.

    Fala rápida gera cue curto: no ep00 a abertura sai a 17,7 char/s. Se
    houver folga até o próximo cue, usá-la é de graça — o texto não muda,
    só fica mais tempo legível.
    """
    for i, c in enumerate(cues):
        limite = (cues[i + 1]["ini"] - GAP_MINIMO
                  if i + 1 < len(cues) else c["fim"] + MAX_DUR)
        if c["fim_trecho"]:
            limite = min(limite, c["fim"])
        dur = c["fim"] - c["ini"]
        if dur <= 0 or len(c["txt"]) / dur <= MAX_CPS:
            continue
        alvo = c["ini"] + min(len(c["txt"]) / MAX_CPS, MAX_DUR)
        c["fim"] = max(c["fim"], min(alvo, limite))
    return cues


def quebra_linhas(txt: str, max_chars: int = MAX_CHARS_LINHA,
                  max_linhas: int = MAX_LINHAS) -> list[str]:
    """Divide o cue em linhas balanceadas, sem passar de `max_chars`.

    Onde a linha quebra é APRESENTAÇÃO, não conteúdo: depende da largura do
    formato, e por isso os limites são parâmetro e vêm de marca/tokens.toml.
    O texto e os tempos do cue não mudam — só o lugar da quebra.

    Isto não é preciosismo. O `.ass` usa `WrapStyle: 2`, que desliga a quebra
    automática do libass: a linha que sair daqui é a linha que vai para a tela,
    inteira. Com os 42 caracteres do 16:9 aplicados ao vertical, 10 das 16
    linhas do ep00 saíam da tela, uma delas com 646 px para fora — texto que
    simplesmente não existia para quem assistisse.

    Escolhe o menor número de linhas que caiba e, entre as divisões possíveis,
    a mais equilibrada.
    """
    if len(txt) <= max_chars:
        return [txt]
    palavras = txt.split()

    def divide(n: int):
        """Melhor divisão em exatamente n linhas, ou None se não couber."""
        alvo = len(txt) / n
        melhor, melhor_custo = None, None

        def busca(inicio: int, restantes: int, atual: list[str]):
            nonlocal melhor, melhor_custo
            if restantes == 1:
                ultima = " ".join(palavras[inicio:])
                if not ultima or len(ultima) > max_chars:
                    return
                linhas = atual + [ultima]
                custo = sum((len(x) - alvo) ** 2 for x in linhas)
                if melhor_custo is None or custo < melhor_custo:
                    melhor, melhor_custo = linhas, custo
                return
            for k in range(inicio + 1, len(palavras) - restantes + 2):
                linha = " ".join(palavras[inicio:k])
                if len(linha) > max_chars:
                    break
                busca(k, restantes - 1, atual + [linha])

        busca(0, n, [])
        return melhor

    minimo = -(-len(txt) // max_chars)          # teto da divisão
    for n in range(max(1, minimo), max_linhas + 1):
        r = divide(n)
        if r:
            return r

    # Não coube no limite: reparte em max_linhas e aceita o estouro, porque
    # perder texto é pior que passar da margem.
    tam = -(-len(palavras) // max_linhas)
    return [" ".join(palavras[i:i + tam])
            for i in range(0, len(palavras), tam)][:max_linhas]


def ts_srt(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def ts_ass(t: float) -> str:
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def escreve_srt(cues, caminho):
    with caminho.open("w", encoding="utf-8") as f:
        for i, c in enumerate(cues, 1):
            f.write(f"{i}\n{ts_srt(c['ini'])} --> {ts_srt(c['fim'])}\n")
            f.write("\n".join(quebra_linhas(c["txt"])) + "\n\n")


CABECALHO_ASS = """[Script Info]
ScriptType: v4.00+
PlayResX: {largura}
PlayResY: {altura}
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Fala,{fonte},{tamanho},{cor_texto},{cor_secundaria},{cor_contorno},{cor_fundo},-1,0,0,0,100,100,0,0,1,{contorno},{sombra},2,{margem_lateral},{margem_lateral},{margem},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


TOKENS = pathlib.Path(__file__).resolve().parent.parent / "marca" / "tokens.toml"


def le_tokens(caminho: pathlib.Path) -> dict:
    """Carrega marca/tokens.toml. Sem ele o script não desenha nada."""
    if not caminho.exists():
        sys.exit(f"Tokens da marca não encontrados: {caminho}\n"
                 f"Ele é a fonte da verdade do visual; sem ele não dá para "
                 f"saber o tamanho nem a margem de cada formato.")
    with caminho.open("rb") as f:
        return tomllib.load(f)


def estilo_do_formato(tokens: dict, formato: str) -> dict:
    """Junta cor, fonte e as medidas do formato pedido, num dicionário só."""
    formatos = tokens.get("formato", {})
    if formato not in formatos:
        sys.exit(f"Formato {formato!r} não existe em {TOKENS.name}. "
                 f"Há: {', '.join(sorted(formatos))}")
    fm, cor = formatos[formato], tokens["cor"]
    return {
        "fonte": tokens["fonte"]["familia"],
        "largura": fm["largura"], "altura": fm["altura"],
        "tamanho": fm["tamanho"], "contorno": fm["contorno"],
        "sombra": fm["sombra"],
        "margem_lateral": fm["margem_lateral"],
        "margem": fm["margem_inferior"],
        "cor_texto": cor["texto"], "cor_secundaria": cor["secundaria"],
        "cor_contorno": cor["contorno"], "cor_fundo": cor["fundo"],
        "chars_por_linha": fm["chars_por_linha"],
        "linhas_max": fm["linhas_max"],
        # Ritmo do cue. Ausentes, valem a norma de leitura do topo deste
        # arquivo — que é o que o 16x9 usa. O vertical declara os seus.
        "chars_por_cue": fm.get("chars_por_cue", MAX_CHARS_CUE),
        "dur_minima": fm.get("dur_minima", MIN_DUR),
    }


def escreve_ass(cues, caminho, estilo):
    with caminho.open("w", encoding="utf-8") as f:
        f.write(CABECALHO_ASS.format(**estilo))
        for c in cues:
            txt = "\\N".join(quebra_linhas(c["txt"],
                                            estilo["chars_por_linha"],
                                            estilo["linhas_max"]))
            f.write(f"Dialogue: 0,{ts_ass(c['ini'])},{ts_ass(c['fim'])},"
                    f"Fala,,0,0,0,,{txt}\n")


ap = argparse.ArgumentParser()
ap.add_argument("words_tsv")
ap.add_argument("--segmentos", default=None,
                help="segmentos.txt do segmenta.py; descarta cues fora da FALA")
ap.add_argument("--formato", default="16x9",
                help="chave de [formato.*] em marca/tokens.toml "
                     "(16x9 para YouTube, 9x16 para Shorts/Reels)")
ap.add_argument("--tokens", default=str(TOKENS),
                help="outro arquivo de tokens da marca")
# Os quatro abaixo sobrescrevem o token, para experimentar sem editar o
# arquivo. O que der certo volta para marca/tokens.toml — não fica no dedo.
ap.add_argument("--fonte", default=None)
ap.add_argument("--tamanho", type=int, default=None)
ap.add_argument("--contorno", type=float, default=None)
ap.add_argument("--sombra", type=float, default=None)
ap.add_argument("--margem", type=int, default=None)
ap.add_argument("--cortes", default=None,
                help="cortes.txt do corta.sh; remapeia os tempos para o "
                     "arquivo cortado e escreve <projeto>/<base>_final.*")
ap.add_argument("--glossario",
                default=str(pathlib.Path(__file__).parent / "glossario.tsv"),
                help="tsv de correções; --glossario '' desliga")
ap.add_argument("--saida", default=None, help="prefixo; padrão out/<projeto>/<base>")
args = ap.parse_args()

wt = pathlib.Path(args.words_tsv)
if not wt.exists():
    sys.exit(f"Sidecar de palavras não encontrado: {wt}\n"
             f"Gere com: ./scripts/transcreve.sh <wav> --word-timestamps")

base = re.sub(r"\.words$", "", wt.stem)
if args.saida:
    prefixo = pathlib.Path(args.saida)
    prefixo.parent.mkdir(parents=True, exist_ok=True)
else:
    print(resumo_projeto(wt, episodio=True))
    prefixo = pasta_episodio(wt) / base

palavras = le_palavras(wt)
n_total = len(palavras)

regioes = []
n_apos_filtro = n_total
if args.segmentos:
    regioes = le_regioes_fala(pathlib.Path(args.segmentos))
    palavras = [p for p in palavras
                if dentro_da_fala(p["ini"], p["fim"], regioes)]
n_apos_filtro = len(palavras)

trocas = []
if args.glossario:
    regras = le_glossario(pathlib.Path(args.glossario))
    palavras, trocas = aplica_glossario(palavras, regras)

fora_do_corte = 0
if args.cortes:
    trechos = le_cortes(pathlib.Path(args.cortes))
    palavras, fora_do_corte = remapeia_cortes(palavras, trechos)
    if not args.saida:
        prefixo = prefixo.with_name(prefixo.name + "_final")

def monta(max_chars_cue: int, min_dur: float):
    return estica_rapidos(
        ajusta_tempos(
            funde_orfaos(
                ajusta_fronteiras(monta_cues(palavras, max_chars_cue),
                                  max_chars_cue),
                max_chars_cue, min_dur),
            min_dur))


estilo = estilo_do_formato(le_tokens(pathlib.Path(args.tokens)), args.formato)
for chave, valor in (("fonte", args.fonte), ("tamanho", args.tamanho),
                     ("contorno", args.contorno), ("sombra", args.sombra),
                     ("margem", args.margem)):
    if valor is not None:
        estilo[chave] = valor

# O .srt sai SEMPRE da norma de leitura, nunca do ritmo do formato. Ele não
# tem formato: é um arquivo só, sobe separado no YouTube e o espectador liga
# e desliga. Se seguisse o formato, gerar o vertical reescreveria em silêncio
# a legenda do longo com cues de três palavras. O .ass é que carrega a
# apresentação — e agora também o ritmo.
cues = monta(MAX_CHARS_CUE, MIN_DUR)
ritmo = (estilo["chars_por_cue"], estilo["dur_minima"])
cues_ass = cues if ritmo == (MAX_CHARS_CUE, MIN_DUR) else monta(*ritmo)

srt = prefixo.with_suffix(".srt")
ass = prefixo.with_suffix(f".{args.formato}.ass")
escreve_srt(cues, srt)
escreve_ass(cues_ass, ass, estilo)

descartadas = n_total - n_apos_filtro
for t in trocas:
    print(f"glossário [{ts_srt(t['ini'])}] {t['de']!r} -> {t['para']!r}")
duracoes = [c["fim"] - c["ini"] for c in cues_ass]
chars = [len(c["txt"]) for c in cues_ass]
cps = [len(c["txt"]) / (c["fim"] - c["ini"]) for c in cues_ass]

print(f"palavras:    {n_total}"
      + (f"  ({descartadas} fora das {len(regioes)} regiões FALA)"
         if args.segmentos else ""))
if args.cortes:
    print(f"cortes:      {len(trechos)} trecho(s), "
          f"{sum(f - i for i, f in trechos):.2f}s mantidos"
          f"  ({fora_do_corte} palavras fora do corte)")
print(f"cues:        {len(cues_ass)}"
      + (f"  no .ass, {len(cues)} no .srt (norma de leitura)"
         if cues_ass is not cues else ""))
print(f"duração:     {min(duracoes):.2f}s a {max(duracoes):.2f}s"
      f"  (média {sum(duracoes)/len(duracoes):.2f}s)")
print(f"caracteres:  {min(chars)} a {max(chars)}"
      f"  (média {sum(chars)/len(chars):.0f})")
# Qual número vigiar depende do ritmo, e usar o errado dá alarme falso.
# Com cue longo o gargalo é a leitura: duas linhas lidas em sacadas, teto
# de MAX_CPS. Com cue curto o char/s SOBE por construção — o texto encolhe
# e a duração encolhe junto — e não quer dizer nada, porque três palavras
# se leem num golpe. Lá o que machuca é o cue piscar, e o piso é dur_minima.
ritmo_proprio = cues_ass is not cues
piso = estilo["dur_minima"]
print(f"leitura:     {min(cps):.1f} a {max(cps):.1f} char/s"
      + (f"  (não é o critério aqui: cue de ~{estilo['chars_por_cue']} "
         f"caracteres lê num golpe)" if ritmo_proprio
         else f"  (confortável até ~{MAX_CPS:.0f})"))
if ritmo_proprio:
    n_pisca = sum(1 for c in cues_ass if c["fim"] - c["ini"] < piso - 1e-6)
    print(f"piso:        {piso:.2f}s  "
          + ("nenhum cue abaixo" if not n_pisca
             else f"{n_pisca} cue abaixo" if n_pisca == 1
             else f"{n_pisca} cues abaixo"))
    for c in cues_ass:
        if c["fim"] - c["ini"] < piso - 1e-6:
            print(f"  pisca ({c['fim'] - c['ini']:.2f}s): "
                  f"[{ts_srt(c['ini'])}] {c['txt']}")
else:
    for c, v in zip(cues_ass, cps):
        if v > MAX_CPS:
            print(f"  rápido demais: [{ts_srt(c['ini'])}] {c['txt']}")
duvidosos = [c for c in cues_ass if c["prob_min"] < 0.5]
for c in duvidosos:
    print(f"  conferir (p={c['prob_min']:.2f}): [{ts_srt(c['ini'])}] {c['txt']}")
print(f"\n{srt}\n{ass}")
