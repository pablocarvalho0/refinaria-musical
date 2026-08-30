#!/usr/bin/env python3
"""Monta a capa a partir de um frame, com a mesma tipografia da cartela.

Duas saídas, porque o YouTube usa duas coisas diferentes:

  16:9 (1280x720)  — é o que a API aceita em thumbnails.set, e o que aparece
                     na página do vídeo, na busca e nas recomendações. O quadro
                     vertical vira um painel sangrando à direita, e o texto
                     ocupa a área que sobra. Melhor que esticar ou barrar.
  9:16 (1080x1920) — para o seletor de capa de Short dentro do Studio.

A tipografia é a mesma do estilo `sereno` das cartelas (EB Garamond + âmbar
amostrado do violão), pelo mesmo motivo que capa de disco e encarte combinam:
se a capa fala outra língua, ela parece de outro vídeo.

Uso:
  python scripts/capa_arte.py frame.png --saida out/capas/arte
"""
import argparse, subprocess, tempfile
from pathlib import Path

MARFIM = "&H00ECF3F7&"
AMBAR  = "&H0057A8E8&"
FUNDO  = "0x16110E"          # near-black quente, o mesmo do quadro de decisão
SERIF  = "EB Garamond 12"
CAPS   = "EB Garamond SC"

OBRA, AUTORIA, FORMATO = "Like a Stone", "AUDIOSLAVE", "versão acústica"
LINHA = "três violões e uma voz"


def cab(w, h):
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: base,{SERIF},80,{MARFIM},{MARFIM},&H00000000&,&H00000000&,0,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def linha(txt):
    return f"Dialogue: 0,0:00:00.00,0:00:10.00,base,,0,0,0,,{txt}"


def rect(w, h):
    return f"m 0 0 l {w} 0 l {w} {h} l 0 {h}"


def ass_169():
    # Texto à esquerda, alinhado numa margem; o painel entra a partir de x=800.
    x = 92
    L = [
        linha(rf"{{\an4\pos({x},188)\fn{CAPS}\fs34\fsp10\c{AMBAR}\bord0\shad0}}{AUTORIA}"),
        linha(rf"{{\an4\pos({x},296)\fn{SERIF}\fs132\fsp1\c{MARFIM}\bord0\shad0}}{OBRA}"),
        linha(rf"{{\an4\pos({x},386)\c{AMBAR}\bord0\shad0\p1}}{rect(150,3)}{{\p0}}"),
        linha(rf"{{\an4\pos({x},452)\fn{SERIF}\i1\fs52\fsp2\c{MARFIM}\alpha&H2A&\bord0\shad0}}{FORMATO}"),
        linha(rf"{{\an4\pos({x},546)\fn{CAPS}\fs30\fsp7\c{MARFIM}\alpha&H60&\bord0\shad0}}{LINHA.upper()}"),
    ]
    return cab(1280, 720) + "\n".join(L) + "\n"


def ass_916():
    # Vertical: bloco embaixo, na mesma banda que a medida de luminância
    # aprovou para a cartela (y 1120..1400).
    L = [
        linha(rf"{{\an5\pos(540,1168)\fn{CAPS}\fs44\fsp13\c{AMBAR}\bord0\shad3\4a&H50&}}{AUTORIA}"),
        linha(rf"{{\an5\pos(540,1288)\fn{SERIF}\fs158\fsp2\c{MARFIM}\bord0\shad4\4a&H40&}}{OBRA}"),
        linha(rf"{{\an5\pos(540,1372)\c{AMBAR}\bord0\shad0\p1}}{rect(260,3)}{{\p0}}"),
        linha(rf"{{\an5\pos(540,1434)\fn{SERIF}\i1\fs62\fsp2\c{MARFIM}\alpha&H28&\bord0\shad3\4a&H50&}}{FORMATO}"),
    ]
    return cab(1080, 1920) + "\n".join(L) + "\n"


def roda(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"ffmpeg falhou:\n{r.stderr[-1200:]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("frame")
    ap.add_argument("--saida", required=True)
    ap.add_argument("--painel", type=int, default=470,
                    help="largura do painel na capa 16:9")
    ap.add_argument("--topo", type=int, default=60,
                    help="quantos px descartar do alto do painel (0 = mantém tudo)")
    a = ap.parse_args()
    saida = Path(a.saida); saida.mkdir(parents=True, exist_ok=True)
    base = Path(a.frame).stem

    with tempfile.TemporaryDirectory() as td:
        p169, p916 = Path(td)/"h.ass", Path(td)/"v.ass"
        p169.write_text(ass_169(), encoding="utf-8")
        p916.write_text(ass_916(), encoding="utf-8")

        # --- 16:9 -------------------------------------------------------
        # ESCALAR PRIMEIRO, RECORTAR DEPOIS. A ordem inversa distorce: recortar
        # 1080x1253 e escalar para 470x720 aplica 0,435 na horizontal e 0,575
        # na vertical, e o rosto sai espremido. Com
        # force_original_aspect_ratio=increase o quadro é escalado até cobrir o
        # painel mantendo a proporção, e só o excedente é cortado.
        w = a.painel
        f169 = saida / f"{base}_1280x720.jpg"
        roda(["ffmpeg", "-v", "error", "-y",
              "-f", "lavfi", "-i", f"color=c={FUNDO}:s=1280x720",
              "-i", a.frame,
              "-filter_complex",
              f"[1:v]scale={w}:720:force_original_aspect_ratio=increase,"
              f"crop={w}:720:(iw-{w})/2:{a.topo},setsar=1[p];"
              f"[0:v][p]overlay=x=1280-{w}:y=0[bg];"
              f"[bg]ass={p169}[v]",
              "-map", "[v]", "-frames:v", "1", "-q:v", "2", str(f169)])

        # --- 9:16 -------------------------------------------------------
        # Aqui vai um scrim em rampa, e ele NÃO é enfeite. A banda y1120-1400
        # é escura e estável nos frames de ABERTURA do vídeo (foi onde a
        # medida de luminância a aprovou), mas numa capa o frame é outro: nos
        # candidatos bons ela cai em cima do tampo do violão, e aí âmbar sobre
        # âmbar desaparece. O scrim devolve o fundo escuro que a tipografia
        # pressupõe, para qualquer frame que se escolha.
        f916 = saida / f"{base}_1080x1920.jpg"
        roda(["ffmpeg", "-v", "error", "-y", "-i", a.frame,
              "-f", "lavfi", "-i", "color=c=black:s=1080x1920",
              "-filter_complex",
              "[1:v]format=rgba,"
              "geq=r=0:g=0:b=0:a='215*pow(clip((Y-700)/1000,0,1),0.95)'[s];"
              f"[0:v][s]overlay=0:0,ass={p916}[v]",
              "-map", "[v]", "-frames:v", "1", "-q:v", "2", str(f916)])

    for f in (f169, f916):
        mb = f.stat().st_size / 1048576
        aviso = "  <-- acima de 2 MB, o YouTube recusa" if mb > 2 else ""
        print(f"{f}  {mb:.2f} MB{aviso}")


if __name__ == "__main__":
    main()
