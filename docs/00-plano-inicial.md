> **Documento histórico.** Escrito antes da validação prática. Contém decisões
> que foram revertidas — notadamente o uso do auto-editor, removido por não
> distinguir pausa de fala de pausa musical. A fonte de verdade atual é o
> CLAUDE.md. Preservado como registro do raciocínio original.

# Fase 0 — Setup mínimo: do S23 ao YouTube

Objetivo único: **tirar um vídeo da galeria do celular, dar tratamento básico e publicar.**
Nada além disso. Tudo o que não serve a esse objetivo está fora, mesmo sendo boa ideia —
está registrado no documento de arquitetura e espera a vez.

Tempo estimado de setup: uma tarde. Tempo por vídeo depois de pronto: minutos de trabalho
seu, mais o tempo de processamento rodando sozinho.

---

## Escopo

**Dentro:** Syncthing, ffmpeg, auto-editor, faster-whisper, script único, upload manual.

**Fora nesta fase:** Demucs, DeepFilterNet, WhisperX, corte semântico, FCPXML, LilyPond,
carrossel, Canva, YouTube Data API. Tudo isso é Fase 1+.

**Critério de sucesso:** você grava, larga o celular, roda um comando, e sai um arquivo
publicável mais os metadados prontos para colar no YouTube.

---

## Aviso sobre os comandos

Os comandos abaixo não foram testados na sua máquina. Nomes de flag mudam entre versões
(o `auto-editor` em particular reorganizou a sintaxe de edição), e instalação de CUDA para
o Whisper é onde mora quase todo o atrito real. **A intenção é rodar isso junto no Claude
Code**, ajustando o que quebrar — o documento serve de roteiro, não de garantia.

---

## Passo 1 — Ingestão com Syncthing

**No Ubuntu:**

```bash
sudo apt update
sudo apt install syncthing
systemctl --user enable --now syncthing
```

Interface em `http://127.0.0.1:8384`.

**No S23:** instalar Syncthing pela Play Store ou F-Droid.

**Configuração:**

1. Parear os dois aparelhos (troca de Device ID; o app tem leitor de QR).
2. No celular, compartilhar a pasta `DCIM/Camera`.
3. **Definir a pasta como *Send Only* no celular.** Sem isso, apagar um arquivo no Ubuntu
   apaga do telefone. É o erro mais caro possível nesta etapa.
4. Nas configurações do app, restringir sincronização a Wi-Fi.
5. No Ubuntu, apontar o destino para `~/video/inbox`.

**Complemento por cabo**, útil dentro de scripts:

```bash
sudo apt install adb
adb devices                                    # autorizar no celular
adb pull /sdcard/DCIM/Camera/<arquivo>.mp4 ~/video/inbox/
```

**Validação:** grave 10 segundos de qualquer coisa e confirme que o arquivo aparece em
`~/video/inbox` sozinho.

---

## Passo 2 — Dependências

```bash
# ffmpeg
sudo apt install ffmpeg
ffmpeg -version

# pipx para CLIs isoladas
sudo apt install pipx
pipx ensurepath

# corte automático de silêncio
pipx install auto-editor
auto-editor --version
```

**Transcrição.** Ambiente virtual próprio, porque puxa PyTorch:

```bash
python3 -m venv ~/video/.venv
source ~/video/.venv/bin/activate
pip install faster-whisper
```

Verificar se a GPU está visível:

```bash
nvidia-smi
python -c "import torch; print(torch.cuda.is_available())"
```

Se der `False`, **não pare aqui**: o script tem fallback para CPU. Um vídeo de 20 minutos
transcreve em alguns minutos em CPU com o modelo `small`. Resolver CUDA é otimização, não
bloqueio — e é exatamente o tipo de coisa para debugar junto depois.

---

## Passo 3 — Estrutura de pastas

```bash
mkdir -p ~/video/{inbox,work,out,scripts}
```

| Pasta | Conteúdo |
|---|---|
| `inbox` | Chega do celular via Syncthing. Não editar nada aqui. |
| `work` | Intermediários. Descartável. |
| `out` | Vídeo final + transcrição. É o que você usa. |
| `scripts` | O pipeline, versionado em git. |

---

## Passo 4 — Script de processamento

`~/video/scripts/processa.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

IN="$1"
BASE=$(basename "$IN" .mp4)
WORK="$HOME/video/work"
OUT="$HOME/video/out"

echo "==> 1/3  Cortando silêncio"
auto-editor "$IN" \
  --margin 0.3sec \
  --no-open \
  -o "$WORK/${BASE}_cut.mp4"

echo "==> 2/3  Normalizando áudio (alvo -14 LUFS / YouTube)"
ffmpeg -y -i "$WORK/${BASE}_cut.mp4" \
  -af "loudnorm=I=-14:TP=-1.5:LRA=11" \
  -c:v copy -c:a aac -b:a 192k \
  "$OUT/${BASE}_final.mp4"

echo "==> 3/3  Extraindo áudio para transcrição"
ffmpeg -y -i "$OUT/${BASE}_final.mp4" \
  -vn -ac 1 -ar 16000 \
  "$WORK/${BASE}.wav"

echo "Pronto: $OUT/${BASE}_final.mp4"
```

```bash
chmod +x ~/video/scripts/processa.sh
```

**Detalhe que importa:** a transcrição sai do vídeo **já cortado**, não do bruto. Assim os
timestamps batem com o vídeo publicado e os capítulos ficam corretos. Fazer na ordem
inversa é o erro clássico aqui.

**Sobre `-c:v copy`:** o vídeo não é reencodado na normalização — só o áudio. Rápido e sem
perda de qualidade.

---

## Passo 5 — Transcrição

`~/video/scripts/transcreve.py`:

```python
#!/usr/bin/env python3
import sys, pathlib
from faster_whisper import WhisperModel

wav = pathlib.Path(sys.argv[1])
out = pathlib.Path.home() / "video/out" / f"{wav.stem}.txt"

try:
    model = WhisperModel("small", device="cuda", compute_type="float16")
except Exception:
    print("CUDA indisponível — usando CPU")
    model = WhisperModel("small", device="cpu", compute_type="int8")

segments, info = model.transcribe(str(wav), language="pt", vad_filter=True)

with out.open("w") as f:
    for s in segments:
        m, sec = divmod(int(s.start), 60)
        h, m = divmod(m, 60)
        f.write(f"[{h:02d}:{m:02d}:{sec:02d}] {s.text.strip()}\n")

print(f"Transcrição: {out}")
```

Uso:

```bash
source ~/video/.venv/bin/activate
python ~/video/scripts/transcreve.py ~/video/work/<nome>.wav
```

Se `small` errar demais o vocabulário musical, subir para `medium`. O `large-v3` é melhor
ainda, mas pesado — e a correção com glossário resolve mais barato que trocar de modelo.

---

## Passo 6 — Metadados

Cole o conteúdo de `~/video/out/<nome>.txt` aqui no chat e peça:

> Corrija o vocabulário de harmonia funcional, depois gere título (3 opções), descrição,
> capítulos com timestamp e 3 trechos candidatos a Reels.

Isso é texto puro entrando e texto puro saindo — consumo de limite baixo. **Nunca suba o
vídeo ou o áudio.**

Guarde os termos que o Whisper errou: eles viram o glossário versionado, que é a primeira
melhoria da Fase 1.

---

## Passo 7 — Publicação

Manual nesta fase, e por escolha. O setup OAuth da YouTube Data API no Google Cloud é um
projeto próprio e não pertence a um "setup mínimo". Com título, descrição e capítulos já
prontos, o upload manual leva poucos minutos.

Automatize depois de dois ou três vídeos publicados — quando o formato dos metadados
estiver estável e você souber o que realmente quer automatizar.

**Thumbnail**, se quiser já nesta fase:

```bash
ffmpeg -i ~/video/out/<nome>_final.mp4 -ss 00:01:23 -vframes 1 ~/video/out/frame.png
```

Suba o PNG aqui e eu componho título e grafismo por cima.

---

## Checklist de validação

- [ ] Vídeo gravado no celular aparece sozinho em `~/video/inbox`
- [ ] Pasta está em *Send Only* no celular
- [ ] `processa.sh` roda até o fim sem erro
- [ ] O corte não comeu início de frase (ajustar `--margin` se comeu)
- [ ] Volume do resultado está consistente
- [ ] Transcrição legível, com erros restritos ao vocabulário técnico
- [ ] Vídeo publicado com capítulos funcionando

---

## O que não fazer nesta fase

Registrado porque a tentação vai aparecer:

- Não instalar Demucs, DeepFilterNet nem WhisperX ainda.
- Não montar template de carrossel antes de o formato editorial existir.
- Não conectar o Canva.
- Não tentar FCPXML nem tocar no Resolve.
- Não caçar CUDA por horas. CPU funciona; siga.

Cada um desses tem lugar reservado no documento de arquitetura. O objetivo aqui é ter algo
rodando de ponta a ponta — porque um pipeline incompleto e sofisticado não publica vídeo.

---

## Próximo passo

Depois de dois vídeos publicados por este fluxo, os próximos itens, em ordem:

1. Glossário de correção alimentado pelos erros reais que apareceram
2. Demucs + DeepFilterNet no áudio
3. WhisperX e corte semântico
