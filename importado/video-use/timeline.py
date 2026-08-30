#!/usr/bin/env python3
"""Filmstrip + forma de onda + palavras, numa PNG só, para um intervalo do vídeo.

Porte de `helpers/timeline_view.py` do projeto browser-use/video-use
(MIT, commit 9575612, ver LICENSE-upstream nesta pasta). Em validação —
não faz parte do fluxo oficial ainda. Ver docs/02-import-video-use.md.

Por que existe: o princípio 2 do CLAUDE.md proíbe subir mídia para o chat.
Isto resolve o problema por outro caminho — condensa um intervalo de vídeo
numa imagem estática que cabe no chat: N frames em miniatura, o envelope
RMS do áudio, os rótulos de palavra com timestamp e as regiões de FALA e
MÚSICA sombreadas.

O que mudou em relação ao upstream, e por quê:

1. **Lê o nosso `.words.tsv`**, não o JSON da ElevenLabs Scribe. Mesmo dado
   (palavra, início, fim), origem local.
2. **Sombreia por classe, não por silêncio.** O upstream pinta todo gap de
   ≥400 ms como candidato a corte. Essa é exatamente a premissa do
   auto-editor que este projeto mediu e descartou: num vídeo de violão a
   pausa longa e limpa é a pausa *musical*, ou seja, o conteúdo. Aqui o
   sombreado vem do `segmentos.txt` — verde é FALA, roxo é MÚSICA — e os
   gaps só são marcados como candidatos **dentro das regiões de FALA**.
3. **Cor da palavra pela probabilidade.** O `.words.tsv` tem a coluna `prob`
   que a Scribe não dá. Palavra abaixo de 0,60 sai em laranja: a imagem
   aponta sozinha onde olhar. Precisão medida de 27% no ep00 — serve para
   priorizar a leitura, não para decidir.

Uso:
    python importado/video-use/timeline.py out/ep00_audio.mp4 30 45
    python importado/video-use/timeline.py out/ep00_audio.mp4 30 45 -o /tmp/t.png
    python importado/video-use/timeline.py out/ep00_audio.mp4 30 45 --frames 12
    python importado/video-use/timeline.py <vídeo> <ini> <fim> \
        --palavras out/ep00.words.tsv --segmentos out/ep00.segmentos.txt

Sem --palavras/--segmentos, resolve sozinho em out/<base>.words.tsv e
out/<base>.segmentos.txt, tirando do nome do vídeo os sufixos que o fluxo
acrescenta (_norm, _audio, _final, _legendado).
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

# Sufixos que processa.sh / audio.sh / corta.sh acrescentam ao nome base.
SUFIXOS = ("_legendado", "_final", "_audio", "_norm")

# Abaixo disto a palavra sai destacada. Mesmo limiar da análise do ep00.
PROB_SUSPEITA = 0.60

# Gap mínimo, em segundos, para marcar candidato a corte dentro da FALA.
GAP_MIN = 0.40

# Um gap só é silêncio se também for silencioso. Energia média dentro do gap,
# em dB relativos ao pico da janela desenhada. NÃO MEDIDO: escolhido para
# rejeitar o caso observado no ep00 (violão a ~-4 dB entre duas frases, dentro
# da região de FALA). Ver docs/02-import-video-use.md, achado 1.
GAP_DB = -25.0


# -------- Resolução de caminhos ---------------------------------------------


def base_do_video(video: Path) -> str:
    """`out/ep00_audio.mp4` -> `ep00`."""
    stem = video.stem
    for s in SUFIXOS:
        if stem.endswith(s):
            return stem[: -len(s)]
    return stem


def resolve_sidecar(video: Path, sufixo: str) -> Path | None:
    base = base_do_video(video)
    for pasta in (video.parent, video.parent.parent / "out", Path.home() / "video" / "out"):
        p = pasta / f"{base}{sufixo}"
        if p.exists():
            return p
    return None


# -------- Leitura dos nossos formatos ---------------------------------------


def le_palavras(caminho: Path | None) -> list[dict]:
    """`.words.tsv` -> [{start, end, word, prob}]. Cabeçalho obrigatório."""
    if caminho is None or not caminho.exists():
        return []
    palavras = []
    with caminho.open(encoding="utf-8") as f:
        for linha in csv.DictReader(f, delimiter="\t"):
            try:
                palavras.append({
                    "start": float(linha["start"]),
                    "end": float(linha["end"]),
                    "word": (linha["word"] or "").strip(),
                    "prob": float(linha.get("prob") or 1.0),
                })
            except (TypeError, ValueError, KeyError):
                continue
    return palavras


def le_segmentos(caminho: Path | None) -> list[dict]:
    """`.segmentos.txt` -> [{classe, inicio, fim}]. Ignora linhas de comentário."""
    if caminho is None or not caminho.exists():
        return []
    segs = []
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        if not linha.strip() or linha.lstrip().startswith("#"):
            continue
        campos = linha.split()
        if len(campos) < 4:
            continue
        try:
            segs.append({
                "classe": campos[0],
                "inicio": hms_para_s(campos[1]),
                "fim": hms_para_s(campos[2]),
            })
        except ValueError:
            continue
    return segs


def hms_para_s(t: str) -> float:
    partes = t.split(":")
    if len(partes) != 3:
        return float(t)
    h, m, s = partes
    return int(h) * 3600 + int(m) * 60 + float(s)


def gaps_na_fala(palavras: list[dict], segs: list[dict], ini: float, fim: float,
                 env: np.ndarray | None = None) -> list[tuple[float, float]]:
    """Gaps >= GAP_MIN entre palavras que também estão em silêncio de fato.

    Três guardas, em ordem de descoberta:

    1. **Dentro de FALA.** Fora dela, silêncio é conteúdo (o upstream não
       tem essa distinção e marcaria a peça inteira).
    2. **Energia abaixo de GAP_DB.** As regiões do `segmentos.txt` são
       grossas — o ep00 tem três para 189s — então "dentro da FALA" ainda
       contém violão entre as frases. Sem esta guarda o porte marcava
       2,3s de violão como candidato a corte, que é literalmente o erro
       do auto-editor que este projeto descartou.
    3. **Sem `segmentos.txt`, devolve vazio.** Prefere não marcar nada a
       marcar errado.
    """
    falas = [s for s in segs if s["classe"] == "FALA"]
    if not falas or not palavras:
        return []

    dentro_da_fala = lambda t: any(f["inicio"] <= t <= f["fim"] for f in falas)

    gaps = []
    anterior = None
    for p in sorted(palavras, key=lambda w: w["start"]):
        if p["end"] <= ini or p["start"] >= fim:
            anterior = p["end"] if anterior is None else max(anterior, p["end"])
            continue
        if anterior is not None and p["start"] - anterior >= GAP_MIN:
            a, b = max(ini, anterior), min(fim, p["start"])
            if b > a and dentro_da_fala((a + b) / 2) and silencioso(env, ini, fim, a, b):
                gaps.append((a, b))
        anterior = p["end"] if anterior is None else max(anterior, p["end"])
    return gaps


def silencioso(env: np.ndarray | None, ini: float, fim: float,
               a: float, b: float) -> bool:
    """Energia média de [a, b] abaixo de GAP_DB em relação ao pico da janela."""
    if env is None or env.size == 0:
        return True                      # sem envelope, não filtra
    n = env.size
    i0 = max(0, min(n - 1, int((a - ini) / max(1e-6, fim - ini) * n)))
    i1 = max(i0 + 1, min(n, int((b - ini) / max(1e-6, fim - ini) * n)))
    media = float(env[i0:i1].mean())
    if media <= 0:
        return True
    return 20.0 * np.log10(media) <= GAP_DB


# -------- Frames e envelope (do upstream, sem mudança de mérito) -------------


def extrai_frames(video: Path, ini: float, fim: float, n: int, destino: Path) -> list[Path]:
    destino.mkdir(parents=True, exist_ok=True)
    n = max(1, n)
    if n == 1:
        tempos = [(ini + fim) / 2.0]
    else:
        passo = (fim - ini) / (n - 1)
        tempos = [ini + i * passo for i in range(n)]

    saidas = []
    for i, t in enumerate(tempos):
        out = destino / f"f_{i:03d}.jpg"
        cmd = ["ffmpeg", "-y", "-ss", f"{t:.3f}", "-i", str(video),
               "-frames:v", "1", "-q:v", "4", "-vf", "scale=320:-2", str(out)]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if out.exists():
            saidas.append(out)
    return saidas


def envelope(video: Path, ini: float, fim: float, amostras: int) -> np.ndarray:
    """RMS por janela do trecho, normalizado em [0, 1]. Mono 16 kHz via ffmpeg."""
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "a.wav"
        cmd = ["ffmpeg", "-y", "-ss", f"{ini:.3f}", "-i", str(video),
               "-t", f"{(fim - ini):.3f}", "-vn", "-ac", "1", "-ar", "16000",
               "-c:a", "pcm_s16le", str(wav)]
        r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if r.returncode != 0 or not wav.exists() or wav.stat().st_size == 0:
            return np.zeros(amostras)

        with wave.open(str(wav), "rb") as w:
            quadros = w.readframes(w.getnframes())

    pcm = np.frombuffer(quadros, dtype=np.int16).astype(np.float32) / 32768.0
    if pcm.size == 0:
        return np.zeros(amostras)

    janela = max(1, pcm.size // amostras)
    util = (pcm.size // janela) * janela
    env = np.sqrt(np.mean(pcm[:util].reshape(-1, janela) ** 2, axis=1))
    if env.size < amostras:
        env = np.pad(env, (0, amostras - env.size))
    else:
        env = env[:amostras]
    return env / env.max() if env.max() > 0 else env


# -------- Desenho ------------------------------------------------------------

FONTES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]

FUNDO = (18, 18, 22)
TEXTO = (235, 235, 235)
FRACO = (110, 110, 120)
SUSPEITA = (255, 150, 60)
ONDA = (140, 180, 255)
COR_FALA = (60, 140, 90, 70)
COR_MUSICA = (120, 70, 160, 70)
COR_GAP = (255, 150, 60, 55)


def fonte(tam: int):
    for fp in FONTES:
        if Path(fp).exists():
            try:
                return ImageFont.truetype(fp, tam)
            except OSError:
                continue
    return ImageFont.load_default()


def desenha(video: Path, ini: float, fim: float, saida: Path, n_frames: int,
            palavras: list[dict], segs: list[dict]) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        frames = extrai_frames(video, ini, fim, n_frames, Path(tmp))
        if not frames:
            sys.exit(f"erro: ffmpeg não extraiu nenhum frame de {video} em {ini}–{fim}s")

        alt_frame = 180
        y_tira, y_onda, alt_onda = 70, 340, 220
        y_regua = y_onda + alt_onda + 2
        largura = 1920
        altura = y_regua + 78

        imgs = []
        for fp in frames:
            img = Image.open(fp).convert("RGB")
            imgs.append(img.resize((int(alt_frame * img.width / img.height), alt_frame),
                                   Image.LANCZOS))

        canvas = Image.new("RGB", (largura, altura), FUNDO)
        draw = ImageDraw.Draw(canvas, "RGBA")
        f_cab, f_peq, f_min = fonte(22), fonte(14), fonte(12)

        # Filmstrip, escalado para caber na largura útil
        x0, x1 = 50, largura - 50
        util = x1 - x0
        total = sum(i.width for i in imgs) + (len(imgs) - 1) * 4
        escala = min(1.0, util / total)
        alt_final = int(alt_frame * escala)
        cursor = x0
        for img in imgs:
            nova = img.resize((max(1, int(img.width * escala)), alt_final), Image.LANCZOS)
            canvas.paste(nova, (cursor, y_tira + (alt_frame - alt_final) // 2))
            cursor += nova.width + max(2, int(4 * escala))
        vao = max(1, cursor - x0 - max(2, int(4 * escala)))

        def t_para_x(t: float) -> int:
            return int(x0 + (t - ini) / max(1e-6, fim - ini) * vao)

        # Faixa de classes, logo acima da onda
        y_faixa = y_onda - 26
        for s in segs:
            a, b = max(ini, s["inicio"]), min(fim, s["fim"])
            if b <= a:
                continue
            cor = COR_FALA if s["classe"] == "FALA" else COR_MUSICA
            draw.rectangle((t_para_x(a), y_faixa, t_para_x(b), y_faixa + 12), fill=cor)
            if t_para_x(b) - t_para_x(a) > 60:
                draw.text((t_para_x(a) + 4, y_faixa - 1), s["classe"], fill=TEXTO, font=f_min)

        # Onda. O envelope vem antes dos gaps porque serve de guarda para eles.
        env = envelope(video, ini, fim, amostras=max(vao, 200))
        draw.rectangle((x0, y_onda, x0 + vao, y_onda + alt_onda), fill=(28, 28, 34))
        gaps = gaps_na_fala(palavras, segs, ini, fim, env)
        for a, b in gaps:
            draw.rectangle((t_para_x(a), y_onda, t_para_x(b), y_onda + alt_onda), fill=COR_GAP)

        meio, amp = y_onda + alt_onda // 2, alt_onda // 2 - 8
        topo = [(x0 + int(i * vao / max(1, len(env) - 1)), meio - int(v * amp))
                for i, v in enumerate(env)]
        base = [(x, 2 * meio - y) for x, y in topo]
        if len(topo) > 1:
            draw.polygon(topo + list(reversed(base)), fill=(*ONDA, 60))
            draw.line(topo, fill=ONDA, width=1)
            draw.line(base, fill=ONDA, width=1)

        # Palavras: rótulo alternando em duas linhas para caber mais texto
        ultimo_x, linha = -9999, 0
        visiveis = [p for p in palavras if p["end"] > ini and p["start"] < fim and p["word"]]
        for p in visiveis:
            cx = (t_para_x(p["start"]) + t_para_x(p["end"])) // 2
            if cx - ultimo_x < 20:
                continue
            cor = SUSPEITA if p["prob"] < PROB_SUSPEITA else TEXTO
            dy = 0 if linha == 0 else 15
            draw.line((cx, y_faixa - 4, cx, y_faixa), fill=FRACO, width=1)
            draw.text((cx + 2, y_faixa - 46 + dy), p["word"], fill=cor, font=f_min)
            ultimo_x, linha = cx, 1 - linha

        # Régua
        for i in range(7):
            frac = i / 6
            xi = x0 + int(frac * vao)
            draw.line((xi, y_regua, xi, y_regua + 6), fill=FRACO, width=1)
            draw.text((xi - 20, y_regua + 8), f"{ini + frac * (fim - ini):.2f}s",
                      fill=FRACO, font=f_peq)

        # Cabeçalho e legenda da imagem
        suspeitas = sum(1 for p in visiveis if p["prob"] < PROB_SUSPEITA)
        draw.text((50, 14), f"{video.name}   {ini:.2f}s → {fim:.2f}s "
                            f"({fim - ini:.2f}s, {len(imgs)} frames, {len(visiveis)} palavras)",
                  fill=TEXTO, font=f_cab)
        draw.text((50, 42), f"verde=FALA  roxo=MUSICA  laranja=gap ≥{GAP_MIN:.2f}s e "
                            f"≤{GAP_DB:.0f}dB dentro da fala ({len(gaps)})"
                            f"   |   palavra laranja: prob < {PROB_SUSPEITA:.2f} ({suspeitas})",
                  fill=FRACO, font=f_peq)

        saida.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(saida, "PNG", optimize=True)
        print(f"salvo: {saida}  ({saida.stat().st_size // 1024} KB, "
              f"{canvas.width}x{canvas.height})")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("video", type=Path)
    ap.add_argument("inicio", type=float)
    ap.add_argument("fim", type=float)
    ap.add_argument("-o", "--saida", type=Path, default=None,
                    help="PNG de saída (padrão: work/timeline/<base>_<ini>-<fim>.png)")
    ap.add_argument("--frames", type=int, default=10)
    ap.add_argument("--palavras", type=Path, default=None)
    ap.add_argument("--segmentos", type=Path, default=None)
    args = ap.parse_args()

    if not args.video.exists():
        sys.exit(f"erro: {args.video} não existe")
    if args.fim <= args.inicio:
        sys.exit("erro: fim tem que ser maior que inicio")

    palavras_tsv = args.palavras or resolve_sidecar(args.video, ".words.tsv")
    segmentos_txt = args.segmentos or resolve_sidecar(args.video, ".segmentos.txt")
    for rotulo, p in (("palavras", palavras_tsv), ("segmentos", segmentos_txt)):
        print(f"{rotulo:10s} {p if p else '(não encontrado — seguindo sem)'}")

    saida = args.saida or (Path.home() / "video" / "work" / "timeline" /
                           f"{base_do_video(args.video)}_{args.inicio:.0f}-{args.fim:.0f}.png")

    desenha(args.video, args.inicio, args.fim, saida, args.frames,
            le_palavras(palavras_tsv), le_segmentos(segmentos_txt))


if __name__ == "__main__":
    main()
