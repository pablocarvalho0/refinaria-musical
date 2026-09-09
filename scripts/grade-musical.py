#!/usr/bin/env python3
"""A grade rítmica de um episódio: andamento, tempos fortes e fronteiras.

Por que existe. Num episódio de fala, a transcrição diz onde cortar — é o
princípio 1 deste projeto. Num episódio instrumental o Whisper devolve zero
palavras, e o único relógio que sobra é o da própria música. Este script é a
fonte da verdade equivalente para esse caso: mede o andamento, deriva a grade
de tempos fortes e aponta onde a música muda de seção.

O uso prático é `--encaixa`: em vez de escolher "o corte fica em 7,0s" no
olho, você diz 7,0 e o script devolve o tempo forte mais próximo, com o erro
em milissegundos. Transição de imagem que cai fora da batida briga com a
música; a que cai em cima some dentro dela, que é o que se quer.

    python scripts/grade-musical.py out/<ep>/<ep>_audio.mp4
    python scripts/grade-musical.py <arquivo> --encaixa 7.0 8.2 15.0 15.5
    python scripts/grade-musical.py <arquivo> --json work/<ep>.grade.json

O `--encaixa` também aceita `nome=tempo`, e aí o relatório sai rotulado.

Duas ressalvas que a medição deste projeto já produziu:

  - o andamento de gravação ao vivo NÃO é constante. O relatório imprime o
    desvio entre batidas; acima de ~5% a grade vira estimativa e um corte
    "na batida" no fim do arquivo pode estar fora. Prefira encaixar em
    tempos fortes próximos de onde a batida foi de fato detectada.
  - a fase do tempo forte é escolhida por energia acumulada, não por
    partitura. Ela acerta quando o bumbo marca o 1; num groove sincopado
    pode errar o deslocamento. Confira ouvindo antes de confiar.
"""
import argparse
import json
import pathlib
import subprocess
import sys
import tempfile

import librosa
import numpy as np

SR = 22050


def carrega(caminho):
    """Devolve o áudio em mono 22,05 kHz, passando pelo ffmpeg se preciso.

    O libsndfile não abre .mp4, e é justamente de .mp4 que se quer medir —
    o entregável, não um .wav intermediário que pode ser de outra versão.
    """
    p = pathlib.Path(caminho)
    if p.suffix.lower() in (".wav", ".flac", ".aiff", ".aif"):
        return librosa.load(str(p), sr=SR, mono=True)[0]
    with tempfile.TemporaryDirectory() as tmp:
        wav = pathlib.Path(tmp) / "a.wav"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(p), "-vn", "-ac", "1",
             "-ar", str(SR), "-c:a", "pcm_s16le", str(wav)], check=True)
        return librosa.load(str(wav), sr=SR, mono=True)[0]


def grade(y, compasso=4):
    env = librosa.onset.onset_strength(y=y, sr=SR, aggregate=np.median)
    bpm, batidas = librosa.beat.beat_track(
        onset_envelope=env, sr=SR, units="time", trim=False)
    bpm = float(np.atleast_1d(bpm)[0])

    # A fase do tempo forte sai da energia acumulada: das `compasso` fases
    # possíveis, a que soma mais força de ataque é a que leva o acento.
    tf = librosa.frames_to_time(np.arange(len(env)), sr=SR, hop_length=512)
    forca = np.interp(batidas, tf, env)
    energia = [float(forca[f::compasso].sum()) for f in range(compasso)]
    fase = int(np.argmax(energia))
    fortes = batidas[fase::compasso]
    return {"bpm": bpm, "batidas": batidas, "fortes": fortes,
            "fase": fase, "energia_fase": energia, "env": env}


def fronteiras(y, batidas):
    """Onde a música muda de seção, em segundos.

    Matriz de recorrência sobre MFCC sincronizado à batida: o pico de
    novidade é o compasso que menos se parece com os que vieram antes.
    Não é análise de forma musical — é 'aqui alguma coisa mudou', que é o
    que interessa para decidir onde a imagem pode mudar junto.
    """
    esp = np.abs(librosa.stft(y, n_fft=2048, hop_length=512))
    mel = librosa.feature.melspectrogram(S=esp ** 2, sr=SR)
    mfcc = librosa.feature.mfcc(S=librosa.power_to_db(mel), n_mfcc=13)
    quadros = librosa.time_to_frames(batidas, sr=SR, hop_length=512)
    mfcc = librosa.util.sync(mfcc, quadros)
    if mfcc.shape[1] < 20:
        return np.array([])
    rec = librosa.segment.recurrence_matrix(mfcc, mode="affinity", sym=True)
    janela, nov = 8, np.zeros(rec.shape[0])
    for i in range(janela, rec.shape[0] - janela):
        nov[i] = rec[i - janela:i, i:i + janela].mean()
    nov = 1 - nov / (nov.max() or 1)
    picos = librosa.util.peak_pick(nov, pre_max=6, post_max=6, pre_avg=6,
                                   post_avg=6, delta=0.05, wait=8)
    return np.array([batidas[p] for p in picos if p < len(batidas)])


def energia_por_compasso(y, fortes):
    """RMS em dB de cada compasso — o arco de dinâmica do episódio."""
    rms = librosa.feature.rms(y=y, hop_length=512)[0]
    t = librosa.frames_to_time(np.arange(len(rms)), sr=SR, hop_length=512)
    linhas = []
    for i in range(len(fortes) - 1):
        m = (t >= fortes[i]) & (t < fortes[i + 1])
        if m.any():
            linhas.append((float(fortes[i]),
                           float(20 * np.log10(rms[m].mean() + 1e-9))))
    return linhas


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("entrada")
    ap.add_argument("--compasso", type=int, default=4,
                    help="batidas por compasso (padrão 4)")
    ap.add_argument("--encaixa", nargs="*", default=[], metavar="[NOME=]SEG",
                    help="tempos a encaixar no tempo forte mais próximo")
    ap.add_argument("--json", help="grava a grade num arquivo")
    ap.add_argument("--arco", action="store_true",
                    help="imprime o RMS de cada compasso")
    a = ap.parse_args()

    y = carrega(a.entrada)
    dur = len(y) / SR
    g = grade(y, a.compasso)
    fortes, batidas = g["fortes"], g["batidas"]
    ib = np.diff(batidas)
    cv = ib.std() / ib.mean() * 100 if len(ib) else 0.0

    print(f"{a.entrada}   {dur:.3f}s")
    print(f"andamento  {g['bpm']:.2f} BPM   batida {60 / g['bpm'] * 1000:.0f} ms"
          f"   compasso {a.compasso}/4 = {60 / g['bpm'] * a.compasso:.3f}s")
    print(f"estabilidade  desvio entre batidas {ib.std() * 1000:.0f} ms "
          f"({cv:.1f}% da média)" + ("   ATENÇÃO: acima de 5%, a grade é "
                                     "estimativa" if cv > 5 else ""))
    print(f"tempos fortes  {len(fortes)} (fase {g['fase']} de {a.compasso}, "
          f"energia {[round(e, 1) for e in g['energia_fase']]})")

    fr = fronteiras(y, batidas)
    if len(fr):
        print("fronteiras de seção  " + "  ".join(f"{f:.2f}" for f in fr))

    print("\ntempos fortes (s)")
    for i in range(0, len(fortes), 8):
        print("  " + "  ".join(f"{v:7.3f}" for v in fortes[i:i + 8]))

    if a.encaixa:
        print("\nencaixe                pedido   tempo forte     erro"
              "      batida      erro")
        for item in a.encaixa:
            nome, _, val = item.rpartition("=")
            t = float(val)
            f = fortes[int(np.argmin(np.abs(fortes - t)))]
            b = batidas[int(np.argmin(np.abs(batidas - t)))]
            marca = ""
            if len(fr) and abs(fr - f).min() < 0.5:
                marca = "  <- fronteira de seção"
            print(f"{(nome or '-'):20s} {t:7.2f}   {f:10.3f} {(f - t) * 1000:+8.0f}ms"
                  f"   {b:9.3f} {(b - t) * 1000:+8.0f}ms{marca}")

    if a.arco:
        print("\narco de dinâmica (RMS por compasso)")
        linhas = energia_por_compasso(y, fortes)
        pico = max(db for _, db in linhas)
        for t, db in linhas:
            print(f"  {t:7.3f}  {db:6.1f} dB  "
                  + "#" * int(max(0, 40 + (db - pico) * 2)))

    if a.json:
        pathlib.Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump({"arquivo": str(a.entrada), "duracao": dur,
                       "bpm": g["bpm"], "compasso": a.compasso,
                       "cv_batida_pct": cv,
                       "batidas": [round(float(v), 4) for v in batidas],
                       "fortes": [round(float(v), 4) for v in fortes],
                       "fronteiras": [round(float(v), 4) for v in fr]},
                      f, ensure_ascii=False, indent=2)
        print(f"\n==> {a.json}")


if __name__ == "__main__":
    sys.exit(main())
