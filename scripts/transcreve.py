#!/usr/bin/env python3
"""
Transcreve áudio com faster-whisper e grava .txt com timestamps.
Entrada oficial: scripts/transcreve.sh (exporta LD_LIBRARY_PATH antes do boot).

Uso: ./transcreve.sh ~/video/work/ep00.wav [--model large-v3] [--compute-type int8_float16]
"""
import argparse
import pathlib
import sys
import os
import time
from contextlib import ExitStack

# O LD_LIBRARY_PATH das libs CUDA é responsabilidade do wrapper
# scripts/transcreve.sh — o linker dinâmico lê a variável no boot do
# processo, então não há como corrigir isso daqui. Só avisamos.
try:
    import nvidia
    _nv = nvidia.__path__[0]          # namespace package: __file__ é None
    if f"{_nv}/cublas/lib" not in os.environ.get("LD_LIBRARY_PATH", ""):
        print("aviso: LD_LIBRARY_PATH sem as libs CUDA — a inferência vai "
              "falhar. Use scripts/transcreve.sh em vez de chamar este "
              "arquivo direto.", file=sys.stderr)
except ImportError:
    pass

from faster_whisper import WhisperModel

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from projeto import pasta_episodio, resumo as resumo_projeto


MODELOS = pathlib.Path.home() / "video" / "models"


def resolve_modelo(nome: str) -> str:
    """Prefere uma cópia local em ~/video/models/faster-whisper-<nome>.

    O download pelo huggingface_hub travou duas vezes na metade do
    large-v3 e não retomou. O modelo foi baixado com curl -C - para
    models/, que fica fora do git (.gitignore) e não depende de rede a
    cada execução. Nome que não bate com um diretório local segue para o
    Hub como antes.
    """
    local = MODELOS / f"faster-whisper-{nome}"
    if (local / "model.bin").exists():
        return str(local)
    return nome


def compute_padrao(modelo: str) -> str:
    """Precisão padrão por modelo, limitada pelos 4 GB da GTX 1650.

    small e medium cabem em float16 com folga (~0,5 e ~1,5 GB de pesos).
    large-v3 em float16 são ~3,1 GB só de pesos, o que não deixa espaço
    para os buffers de atenção do beam search — por isso int8_float16,
    que guarda os pesos quantizados (~1,6 GB) e faz a conta em float16.

    A checagem é por substring, não por prefixo: o modelo pode chegar
    como caminho local (models/faster-whisper-large-v3).
    """
    return "int8_float16" if "large" in modelo else "float16"


p = argparse.ArgumentParser()
p.add_argument("wav")
p.add_argument("--model", default="small",
               help="small (rápido) | medium (melhor p/ termos técnicos) | large-v3")
p.add_argument("--compute-type", default=None,
               help="float16 | int8_float16 | int8 | float32. "
                    "Padrão: float16, ou int8_float16 para large-* (VRAM de 4 GB)")
p.add_argument("--word-timestamps", action="store_true",
               help="alinhamento por palavra (usado pela segmentação fala/música)")
args = p.parse_args()

wav = pathlib.Path(args.wav)
if not wav.exists():
    sys.exit(f"Arquivo não encontrado: {wav}")

modelo = resolve_modelo(args.model)
compute = args.compute_type or compute_padrao(args.model)

# A transcrição é do episódio, e vai para a pasta dele: um master gera
# várias entregas, e out/ raso já tinha 40 arquivos de 4 masters.
print(resumo_projeto(wav, episodio=True))
out = pasta_episodio(wav) / f"{wav.stem}.txt"

# Sidecar legível por máquina: início, fim e texto de cada segmento, em
# segundos com casas decimais. O .txt existe para o humano colar no chat e
# só carrega o início arredondado ao segundo; a segmentação fala/música
# precisa do fim e da precisão sub-segundo para medir os gaps.
tsv = pathlib.Path.home() / "video" / "work" / f"{wav.stem}.segments.tsv"
tsv.parent.mkdir(parents=True, exist_ok=True)

# Sidecar de palavras: um registro por palavra, com início, fim e a
# probabilidade que o modelo deu a ela. É o insumo da legenda — os
# segmentos do Whisper chegam a 29s e 427 caracteres no ep00, o que não
# cabe em tela nem de longe. Só é escrito com --word-timestamps, porque
# sem a flag o faster-whisper deixa seg.words vazio.
words_tsv = pathlib.Path.home() / "video" / "work" / f"{wav.stem}.words.tsv"

# Baixa/carrega o modelo primeiro — falha aqui é de rede, não de device
t0 = time.monotonic()
try:
    model = WhisperModel(modelo, device="cuda", compute_type=compute)
    device = f"GPU {compute}"
except (RuntimeError, ValueError) as e:
    # RuntimeError é o que o CTranslate2 lança quando CUDA falta;
    # ValueError quando o compute_type não é suportado pelo device.
    print(f"[{args.model}] CUDA indisponível ou compute_type recusado: {e}")
    compute = "int8"          # único que vale a pena no CPU
    model = WhisperModel(modelo, device="cpu", compute_type=compute)
    device = f"CPU {compute}"
t_load = time.monotonic() - t0
print(f"[{args.model}] {device} — modelo carregado em {t_load:.1f}s")

# vad_filter descarta silêncio antes de transcrever: mais rápido e evita
# que o Whisper "alucine" texto em trechos sem fala.
segments, info = model.transcribe(
    str(wav),
    language="pt",
    vad_filter=True,
    beam_size=5,
    word_timestamps=args.word_timestamps,
)

print(f"Duração: {info.duration:.0f}s — transcrevendo...")


def hms(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


# O generator é preguiçoso: a inferência só acontece aqui dentro, então o
# cronômetro tem que envolver o laço, não a chamada de transcribe().
t1 = time.monotonic()
n_words = 0
with ExitStack() as stack:
    f = stack.enter_context(out.open("w", encoding="utf-8"))
    g = stack.enter_context(tsv.open("w", encoding="utf-8"))
    g.write("start\tend\ttext\n")
    w = None
    if args.word_timestamps:
        w = stack.enter_context(words_tsv.open("w", encoding="utf-8"))
        w.write("start\tend\tword\tprob\n")
    for seg in segments:
        texto = seg.text.strip()
        line = f"[{hms(seg.start)}] {texto}"
        f.write(line + "\n")
        g.write(f"{seg.start:.3f}\t{seg.end:.3f}\t{texto}\n")
        if w is not None:
            # seg.words pode vir None num segmento sem alinhamento
            for word in (seg.words or []):
                w.write(f"{word.start:.3f}\t{word.end:.3f}\t"
                        f"{word.word.strip()}\t{word.probability:.3f}\n")
                n_words += 1
        print(line)
t_infer = time.monotonic() - t1

print(f"\nTranscrição: {out}")
print(f"Segmentos:   {tsv}")
if args.word_timestamps:
    print(f"Palavras:    {words_tsv}  ({n_words} palavras)")
print(f"\nmodelo={args.model}  compute_type={compute}  device={device.split()[0]}")
print(f"carga    {t_load:7.1f}s")
print(f"inferência {t_infer:5.1f}s  para {info.duration:.1f}s de áudio  "
      f"= {t_infer / max(info.duration, 1e-9):.3f}x tempo real "
      f"({info.duration / max(t_infer, 1e-9):.1f}x mais rápido que o relógio)")
