#!/usr/bin/env python3
"""
Monta legendas (.srt e .ass) a partir do sidecar de palavras do Whisper.

Os segmentos que o Whisper devolve não servem como legenda: no ep00 o
primeiro tem 29,00s e 427 caracteres. O que serve é o alinhamento por
palavra (`transcreve.sh --word-timestamps`), reagrupado aqui por regras
de leitura explícitas.

Uso: python scripts/legenda.py work/ep00.words.tsv \
         --segmentos out/ep00.segmentos.txt
"""
import argparse
import pathlib
import re
import sys

# Regras de leitura. Os números seguem a prática de legendagem para vídeo
# (BBC/Netflix convergem nesta faixa): duas linhas de no máximo ~42
# caracteres, entre 1 e 6 segundos na tela. Ficam aqui em cima porque são
# o que se ajusta depois de ver o resultado na tela.
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


def monta_cues(palavras: list[dict]) -> list[dict]:
    """Agrupa palavras em cues. Fecha em pontuação, pausa ou teto."""
    cues, buf = [], []

    def texto(buf):
        return " ".join(p["txt"] for p in buf)

    for i, p in enumerate(palavras):
        buf.append(p)
        t = texto(buf)
        prox = palavras[i + 1] if i + 1 < len(palavras) else None

        fecha = False
        if prox is None:
            fecha = True
        elif t and t[-1] in FORTE:
            fecha = True
        elif t and t[-1] in FRACA and len(t) >= MAX_CHARS_CUE * CHEIO:
            fecha = True
        elif prox["ini"] - p["fim"] > GAP_QUEBRA:
            fecha = True
        elif len(t) + 1 + len(prox["txt"]) > MAX_CHARS_CUE:
            fecha = True
        elif prox["fim"] - buf[0]["ini"] > MAX_DUR:
            fecha = True
        elif p.get("corte_depois"):
            fecha = True

        if fecha:
            cues.append({"ini": buf[0]["ini"], "fim": buf[-1]["fim"],
                         "txt": t,
                         "fim_trecho": bool(p.get("corte_depois")),
                         "prob_min": min(x["prob"] for x in buf)})
            buf = []
    return cues


def funde_orfaos(cues: list[dict]) -> list[dict]:
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
        orfao = (c["fim_trecho"] and c["fim"] - c["ini"] < MIN_DUR
                 and anterior is not None and not anterior["fim_trecho"]
                 and len(anterior["txt"]) + 1 + len(c["txt"]) <= MAX_CHARS_CUE)
        if orfao:
            anterior["txt"] += " " + c["txt"]
            anterior["fim"] = c["fim"]
            anterior["fim_trecho"] = True
            anterior["prob_min"] = min(anterior["prob_min"], c["prob_min"])
            continue
        saida.append(c)
    return saida


def ajusta_tempos(cues: list[dict]) -> list[dict]:
    """Dá folga no fim e garante MIN_DUR, sem invadir o cue seguinte."""
    for i, c in enumerate(cues):
        limite = (cues[i + 1]["ini"] - GAP_MINIMO
                  if i + 1 < len(cues) else float("inf"))
        if c["fim_trecho"]:
            limite = min(limite, c["fim"])
        c["fim"] = min(c["fim"] + FOLGA_FIM, limite)
        if c["fim"] - c["ini"] < MIN_DUR:
            c["fim"] = min(c["ini"] + MIN_DUR, limite)
        # limite pode ser menor que o início quando duas palavras se
        # encavalam no alinhamento; nesse caso o cue fica com o que tem.
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


def quebra_linhas(txt: str) -> list[str]:
    """Divide em até MAX_LINHAS no espaço mais balanceado."""
    if len(txt) <= MAX_CHARS_LINHA:
        return [txt]
    palavras = txt.split()
    melhor, melhor_custo = None, None
    for k in range(1, len(palavras)):
        a, b = " ".join(palavras[:k]), " ".join(palavras[k:])
        if len(a) > MAX_CHARS_LINHA or len(b) > MAX_CHARS_LINHA:
            continue
        custo = abs(len(a) - len(b))
        if melhor_custo is None or custo < melhor_custo:
            melhor, melhor_custo = (a, b), custo
    if melhor:
        return list(melhor)
    # Não coube em duas linhas dentro do limite: divide no meio e aceita
    # o estouro em vez de perder texto.
    meio = len(palavras) // 2
    return [" ".join(palavras[:meio]), " ".join(palavras[meio:])]


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
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Fala,{fonte},{tamanho},&H00FFFFFF,&H000000FF,&H00101010,&H96000000,-1,0,0,0,100,100,0,0,1,{contorno},{sombra},2,140,140,{margem},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def escreve_ass(cues, caminho, fonte, tamanho, contorno, sombra, margem):
    with caminho.open("w", encoding="utf-8") as f:
        f.write(CABECALHO_ASS.format(fonte=fonte, tamanho=tamanho,
                                     contorno=contorno, sombra=sombra,
                                     margem=margem))
        for c in cues:
            txt = "\\N".join(quebra_linhas(c["txt"]))
            f.write(f"Dialogue: 0,{ts_ass(c['ini'])},{ts_ass(c['fim'])},"
                    f"Fala,,0,0,0,,{txt}\n")


ap = argparse.ArgumentParser()
ap.add_argument("words_tsv")
ap.add_argument("--segmentos", default=None,
                help="segmentos.txt do segmenta.py; descarta cues fora da FALA")
ap.add_argument("--fonte", default="Inter")
ap.add_argument("--tamanho", type=int, default=54)
ap.add_argument("--contorno", type=float, default=3.2)
ap.add_argument("--sombra", type=float, default=1.0)
ap.add_argument("--margem", type=int, default=90)
ap.add_argument("--cortes", default=None,
                help="cortes.txt do corta.sh; remapeia os tempos para o "
                     "arquivo cortado e escreve out/<base>_final.*")
ap.add_argument("--glossario",
                default=str(pathlib.Path(__file__).parent / "glossario.tsv"),
                help="tsv de correções; --glossario '' desliga")
ap.add_argument("--saida", default=None, help="prefixo; padrão out/<base>")
args = ap.parse_args()

wt = pathlib.Path(args.words_tsv)
if not wt.exists():
    sys.exit(f"Sidecar de palavras não encontrado: {wt}\n"
             f"Gere com: ./scripts/transcreve.sh <wav> --word-timestamps")

base = re.sub(r"\.words$", "", wt.stem)
prefixo = (pathlib.Path(args.saida) if args.saida
           else pathlib.Path.home() / "video" / "out" / base)
prefixo.parent.mkdir(parents=True, exist_ok=True)

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

cues = estica_rapidos(ajusta_tempos(funde_orfaos(monta_cues(palavras))))

srt = prefixo.with_suffix(".srt")
ass = prefixo.with_suffix(".ass")
escreve_srt(cues, srt)
escreve_ass(cues, ass, args.fonte, args.tamanho,
            args.contorno, args.sombra, args.margem)

descartadas = n_total - n_apos_filtro
for t in trocas:
    print(f"glossário [{ts_srt(t['ini'])}] {t['de']!r} -> {t['para']!r}")
duracoes = [c["fim"] - c["ini"] for c in cues]
chars = [len(c["txt"]) for c in cues]
cps = [len(c["txt"]) / (c["fim"] - c["ini"]) for c in cues]

print(f"palavras:    {n_total}"
      + (f"  ({descartadas} fora das {len(regioes)} regiões FALA)"
         if args.segmentos else ""))
if args.cortes:
    print(f"cortes:      {len(trechos)} trecho(s), "
          f"{sum(f - i for i, f in trechos):.2f}s mantidos"
          f"  ({fora_do_corte} palavras fora do corte)")
print(f"cues:        {len(cues)}")
print(f"duração:     {min(duracoes):.2f}s a {max(duracoes):.2f}s"
      f"  (média {sum(duracoes)/len(duracoes):.2f}s)")
print(f"caracteres:  {min(chars)} a {max(chars)}"
      f"  (média {sum(chars)/len(chars):.0f})")
print(f"leitura:     {min(cps):.1f} a {max(cps):.1f} char/s"
      f"  (confortável até ~17)")
acima = [c for c, v in zip(cues, cps) if v > 17]
for c in acima:
    print(f"  rápido demais: [{ts_srt(c['ini'])}] {c['txt']}")
duvidosos = [c for c in cues if c["prob_min"] < 0.5]
for c in duvidosos:
    print(f"  conferir (p={c['prob_min']:.2f}): [{ts_srt(c['ini'])}] {c['txt']}")
print(f"\n{srt}\n{ass}")
