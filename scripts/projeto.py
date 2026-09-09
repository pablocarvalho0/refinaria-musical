#!/usr/bin/env python3
"""Pasta de saída por projeto — espelho Python de projeto_de, do lib.sh.

A regra está escrita duas vezes porque metade do pipeline é shell e a
outra metade é Python, e obrigar o processa.sh a subir um interpretador
só para descobrir onde escrever seria pior. O que sustenta o espelho não
é disciplina: é o scripts/testa-projeto.sh, que roda os dois lados sobre
a mesma bateria de casos e falha se discordarem em um só.

O porquê dos quatro degraus está no cabeçalho do lib.sh, e não se repete
aqui de propósito — comentário duplicado envelhece pela metade. O mesmo
vale para RODADA e a separação entre pasta_episodio e pasta_projeto.

Uso:  python scripts/projeto.py <caminho>              # nome do projeto
      python scripts/projeto.py --dir <caminho>        # onde escrever
      python scripts/projeto.py --episodio <caminho>   # a raiz do episódio
"""
import os
import pathlib
import re
import sys

RAIZ_OUT = pathlib.Path(os.environ.get(
    "RAIZ_OUT", pathlib.Path.home() / "video" / "out")).expanduser().absolute()
# Os sufixos com ponto importam tanto quanto os com underscore: sem eles,
# ep00.16x9.ass abria uma pasta out/ep00.16x9/.
SUFIXOS_ETAPA = ("_norm", "_audio", "_final", "_legendado", "_work48",
                 ".16x9", ".9x16", ".words", ".segments", ".segmentos")
RE_VARIANTE = re.compile(r"\.v\d+$")


def projeto_de(caminho) -> tuple[str, str]:
    """Devolve (nome_do_projeto, como_foi_resolvido)."""
    if os.environ.get("PROJETO"):
        return os.environ["PROJETO"], "variável PROJETO"

    p = pathlib.Path(caminho)
    abs_ = pathlib.Path(os.path.normpath(p.expanduser().absolute()))

    # 2. já está dentro de out/<X>/
    try:
        resto = abs_.relative_to(RAIZ_OUT)
    except ValueError:
        pass
    else:
        if len(resto.parts) > 1:
            return resto.parts[0], "pasta de origem"

    base = p.name
    if "." in base:
        base = base[: base.rindex(".")]

    # 3. maior pasta existente que prefixa o basename
    melhor = ""
    if RAIZ_OUT.is_dir():
        for d in RAIZ_OUT.iterdir():
            if not d.is_dir():
                continue
            n = d.name
            if base == n or base.startswith(n + "_") or base.startswith(n + "."):
                if len(n) > len(melhor):
                    melhor = n
    if melhor:
        return melhor, "pasta existente que prefixa o nome"

    # 4. basename sem sufixo de etapa
    mudou = True
    while mudou:
        mudou = False
        for s in SUFIXOS_ETAPA:
            if base.endswith(s):
                base, mudou = base[: -len(s)], True
        if RE_VARIANTE.search(base):
            base, mudou = RE_VARIANTE.sub("", base), True
    return base, "nome do arquivo"


RE_RODADA = re.compile(r"^[A-Za-z0-9._-]+$")


def rodada() -> str:
    """O slug da rodada de teste, ou "" fora de teste. Ver lib.sh."""
    r = os.environ.get("RODADA", "")
    if r and (not RE_RODADA.match(r) or ".." in r):
        sys.exit(f"RODADA inválida: {r!r} — só letras, números, . _ -")
    return r


def pasta_episodio(caminho) -> pathlib.Path:
    """out/<ep>/ — a casa dos textos do episódio, imune a RODADA.

    A transcrição, o .segmentos.txt, o .srt e o .ass são do episódio
    inteiro, não de um render: são iguais para todas as variantes que se
    está comparando. Se seguissem a rodada, cada rodada teria a sua cópia
    e a próxima não acharia a anterior.
    """
    nome, _ = projeto_de(caminho)
    destino = RAIZ_OUT / nome
    destino.mkdir(parents=True, exist_ok=True)
    return destino


def pasta_projeto(caminho) -> pathlib.Path:
    """Onde ESTA execução escreve: out/<ep>/ ou out/<ep>/testes/<rodada>/."""
    destino = pasta_episodio(caminho)
    r = rodada()
    if r:
        destino = destino / "testes" / r
        destino.mkdir(parents=True, exist_ok=True)
    return destino


def resumo(caminho, episodio: bool = False) -> str:
    """A linha de log que todo script imprime antes de escrever.

    `episodio=True` para quem escreve texto do episódio inteiro: aí a
    rodada é anunciada como ignorada, em vez de silenciosamente não
    aplicada. Rodada que não vale em algum lugar tem de dizer isso.
    """
    nome, origem = projeto_de(caminho)
    linhas = [f"==> Projeto: {nome}  (por {origem})"]
    r = rodada()
    if r and episodio:
        linhas.append(f"    Rodada {r} não vale aqui: texto é do episódio")
        linhas.append(f"    Saída em: out/{nome}/")
    elif r:
        linhas.append(f"    Rodada de teste: {r}  — NÃO é entregável")
        linhas.append(f"    Saída em: out/{nome}/testes/{r}/")
    else:
        linhas.append(f"    Saída em: out/{nome}/")
    return "\n".join(linhas)


if __name__ == "__main__":
    args = sys.argv[1:]
    modo = "nome"
    if args and args[0] in ("--dir", "--episodio"):
        modo, args = args[0].lstrip("-"), args[1:]
    if len(args) != 1:
        sys.exit("uso: projeto.py [--dir|--episodio] <caminho>")
    if modo == "dir":
        print(pasta_projeto(args[0]))
    elif modo == "episodio":
        print(pasta_episodio(args[0]))
    else:
        print(projeto_de(args[0])[0])
