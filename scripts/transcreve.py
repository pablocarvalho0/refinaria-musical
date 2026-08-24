#!/usr/bin/env python3
"""
Transcreve áudio com faster-whisper e grava .txt com timestamps.
Entrada oficial: scripts/transcreve.sh (exporta LD_LIBRARY_PATH antes do boot).
Uso: ./transcreve.sh ~/video/work/20260824_135542.wav [--model medium]
"""
import argparse
import pathlib
import sys
import os

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

p = argparse.ArgumentParser()
p.add_argument("wav")
p.add_argument("--model", default="small",
               help="small (rápido) | medium (melhor p/ termos técnicos) | large-v3")
args = p.parse_args()

wav = pathlib.Path(args.wav)
if not wav.exists():
    sys.exit(f"Arquivo não encontrado: {wav}")

out = pathlib.Path.home() / "video" / "out" / f"{wav.stem}.txt"
out.parent.mkdir(parents=True, exist_ok=True)

# Baixa/carrega o modelo primeiro — falha aqui é de rede, não de device
try:
    model = WhisperModel(args.model, device="cuda", compute_type="float16")
    print(f"[{args.model}] GPU")
except RuntimeError as e:
    # RuntimeError é o que o CTranslate2 lança quando CUDA falta
    print(f"[{args.model}] CPU — CUDA indisponível: {e}")
    model = WhisperModel(args.model, device="cpu", compute_type="int8")

# vad_filter descarta silêncio antes de transcrever: mais rápido e evita
# que o Whisper "alucine" texto em trechos sem fala.
segments, info = model.transcribe(
    str(wav),
    language="pt",
    vad_filter=True,
    beam_size=5,
)

print(f"Duração: {info.duration:.0f}s — transcrevendo...")

def hms(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"

with out.open("w", encoding="utf-8") as f:
    for seg in segments:
        line = f"[{hms(seg.start)}] {seg.text.strip()}"
        f.write(line + "\n")
        print(line)

print(f"\nTranscrição: {out}")