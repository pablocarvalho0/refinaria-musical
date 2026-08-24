# CLAUDE.md

Contexto operacional deste projeto. Leia antes de sugerir qualquer coisa.

## O que é

Pipeline de produção de vídeo para um canal de **harmonia funcional** (violão + fala),
com destino YouTube (longo) e Instagram (curto). Série planejada: ~47 episódios.
Operação solo. Gravação no celular, processamento local no Ubuntu.

## Princípios que governam as decisões

**1. A transcrição é a fonte da verdade.**
Depois que o áudio vira texto com timestamps, corte, capítulo, legenda, descrição e
carrossel são derivados do mesmo arquivo. Erro na transcrição contamina tudo a jusante.

**2. Bits pesados nunca sobem para o chat.**
O .mp4 fica na máquina. Para o Claude vai texto e, no máximo, um frame PNG.
Nunca sugerir enviar vídeo ou áudio para análise.

**3. Script escrito uma vez roda para sempre.**
Só volta ao Claude o que exige julgamento: escolher trechos, escrever título, revisar.
Tarefa determinística não deve consumir limite de uso.

## Ambiente

| Item | Valor |
|---|---|
| OS | Ubuntu 24.04 (noble) |
| Máquina | Acer Nitro AN515-57, GPU híbrida Intel + NVIDIA |
| GPU | GTX 1650 4 GB, driver 580.173.02, CUDA 13.0 |
| ffmpeg | 6.1.1-3ubuntu5 (repo Ubuntu), com NVENC h264/hevc/av1 |
| Python | venv em `~/video/.venv` (3.12.3) |
| faster-whisper | 1.2.1 |
| Syncthing | 1.27.2-ds4 (Ubuntu) ↔ Syncthing-Fork 2.1.3 (Android) |
| Celular | Galaxy S23 (SM-S911B), grava UHD 60 HEVC, sem HDR |

### Regras de ambiente — não violar

- **Sempre ativar o venv** antes de rodar Python: `cd ~/video && source .venv/bin/activate`
- **NÃO usar mise neste projeto.** Já foi tentado; o `mise.toml` desativa o venv e causa
  `ModuleNotFoundError`. Foi removido de propósito. O venv já pina o interpretador.
- **NÃO instalar auto-editor de volta.** Foi removido por decisão técnica (ver abaixo).
- **pipx para executáveis, venv para imports.** Não misturar.
- O pacote `nvidia` é **namespace package**: `nvidia.__file__` é `None`.
  Usar `nvidia.__path__[0]`.
- **Modelos Whisper ficam em `~/video/models/`**, fora do git. O `transcreve.py`
  resolve `--model large-v3` para `models/faster-whisper-large-v3/` quando o
  diretório existe, senão vai ao Hub. Motivo: o download pelo `huggingface_hub`
  travou duas vezes na metade do large-v3 e a segunda tentativa nem retomou —
  começou um `.incomplete` novo do zero. `curl -L -C - --retry 20` retomou de
  1,27 GB e completou a 9,7 MB/s, 5x mais rápido. O nome do blob no cache do HF
  **é o SHA256 do arquivo**, então dá para verificar a emenda:
  `sha256sum model.bin` bateu com `69f74147…`.

### Gotcha do CUDA

O CTranslate2 carrega cuBLAS/cuDNN **preguiçosamente** e não olha dentro do venv.
Construir o `WhisperModel` não falha; a falha só aparece na primeira inferência, com
`RuntimeError: Library libcublas.so.12 is not found`.

Solução: exportar `LD_LIBRARY_PATH` **antes** do processo Python iniciar (o linker
dinâmico lê a variável no boot do processo; mudar depois não tem efeito):

```bash
NV=$(python -c "import nvidia; print(nvidia.__path__[0])")
export LD_LIBRARY_PATH="$NV/cublas/lib:$NV/cudnn/lib:${LD_LIBRARY_PATH:-}"
```

## Estrutura

```
~/video/
├── inbox/      # chega do celular via Syncthing (Receive Only). NÃO editar.
├── work/       # intermediários e .wav. Descartável.
├── out/        # entregáveis: _norm.mp4, _audio.mp4, _final.mp4, .txt
├── scripts/    # versionado
├── models/     # modelos Whisper baixados. Descartável (redownload).
└── .venv/      # ignorado pelo git
```

`inbox`, `work`, `out`, `models` e `.venv` estão no `.gitignore`.
**Nunca versionar mídia nem pesos de modelo.**

## Fluxo

```bash
cd ~/video && source .venv/bin/activate

# 1. Normaliza: 4K HEVC -> 1080p60 H.264 + áudio a -14 LUFS + extrai .wav
./scripts/processa.sh ~/video/inbox/<arquivo>.mp4

# 2. Transcreve (GPU)
./scripts/transcreve.sh ~/video/work/<arquivo>.wav

# 3. Humano cola a transcrição no chat -> recebe cortes.txt

# 4. Aplica os cortes
./scripts/corta.sh ~/video/out/<arquivo>_norm.mp4 ~/video/work/cortes.txt

# 5. Tratamento de áudio por classe (opcional, ver Fase 1)
python scripts/segmenta.py ~/video/work/<arquivo>.wav   # gera work/segmentos.txt
./scripts/audio.sh ~/video/work/<arquivo>.mp4           # gera out/<arquivo>_audio.mp4

# Medir loudness de qualquer arquivo, separando fala de música:
./scripts/mede-audio.sh <arquivo> ~/video/work/segmentos.txt
```

Formato do `cortes.txt` — trechos a **MANTER**, um por linha:

```
00:00:04  00:00:12
00:00:23  00:03:09
```

## Decisões tomadas — não reabrir sem motivo novo

### auto-editor foi removido

Corte por energia de áudio não distingue **pausa de fala** (lixo) de **pausa musical**
(conteúdo). Num vídeo de violão ele corta justamente onde não deve — e pior, numa pausa
musical o silêncio é mais limpo que numa pausa de fala, então ele corta com mais confiança
onde mais erra.

Medido: reduziu 3,8s de 189,6s (2%) e cortou nos lugares errados. Não existe valor de
`--margin` ou `--silent-threshold` que resolva, porque a diferença não está no áudio,
está no significado.

**Substituído por corte semântico:** o Whisper só transcreve fala, então a transcrição
delimita sozinha as regiões musicais. Onde não há texto, é música — não cortar.

### x264 em vez de NVENC

Medido no mesmo fonte (1.4 GB, 4K60 HEVC, 3min09):

| Encoder | Saída | Tempo | Gerações |
|---|---|---|---|
| `h264_nvenc -cq 23` | 357 MB | 1m14s | 1 |
| NVENC + auto-editor | 83 MB | 3m40s | 3 |
| **`libx264 -crf 23 -preset fast`** | **84 MB** | **2m21s** | **1** |

O NVENC da GTX 1650 (Turing) desperdiça bitrate; `-b:v 0` não corrigiu. O x264 dá o mesmo
tamanho do caminho de três gerações, em menos tempo e com uma geração só de perda.

A GPU continua sendo usada para **decodificar** (`-hwaccel cuda`), que é a parte cara.

### Ordem: normalizar antes de cortar

Ordem inversa foi testada e é inviável: qualquer ferramenta que decodifique 4K60 HEVC em
software leva dezenas de minutos. Depois do downscale para 1080p H.264, a mesma operação
leva ~2 min.

### Resolve MCP descartado

Exige Resolve **Studio** (pago); a edição gratuita não tem external scripting.
Reabrir só se a licença for comprada.

### Reconhecimento automático de acordes descartado

`autochord` cobre 25 classes (12 tríades maiores, 12 menores, "sem acorde") a ~67% de
acurácia. Sem sétimas, extensões ou inversões — inútil para harmonia funcional.

Alternativa adotada: o autor **já sabe os acordes**; o que falta é *quando*. A narração
resolve — ao dizer "aqui entra o empréstimo modal", o Whisper carimba o timestamp.

## Documentos

- `docs/00-plano-inicial.md` — registro histórico. **Superado.** Descreve o
  auto-editor como parte do escopo; foi removido. Não seguir.
- `docs/01-arquitetura-segmentacao.md` — arquitetura da Fase 1, com as medições
  dos passos 1 e 2.

## Segmentação fala/música (Fase 1 — passo 2 feito)

A transcrição particiona o vídeo em duas classes: onde há texto é FALA, onde
não há é MÚSICA. Cada classe recebe cadeia de processamento própria, e os
segmentos são reunidos ao final.

Supera a regra defensiva anterior ("a transcrição diz onde não cortar").

**Passo 1 — medir a zona cinzenta.** `scripts/segmenta.py`. Medido duas vezes no
mesmo episódio (`video_0`, 189,6s): 3,0% com `small`, **3,2% com `large-v3`**.
Abaixo do critério de 10%. O modelo maior *não* melhorou a fronteira: moveu o fim
da fala de 35,140s para 34,600s e a ambiguidade subiu de 4,46s para 5,00s.

O custo é **por fronteira (~5s), não por minuto**. A regra derivada segue valendo:
a segmentação só por transcrição se sustenta enquanto a alternância fala/música
for **mais espaçada que ~50s**. Este episódio tem **uma única fronteira medível**
e é o caso favorável extremo. n=1 — a medição autoriza o passo 2, não a
generalização.

**Passo 2 — cadeias de áudio por classe.** `scripts/audio.sh`, feito e medido
(ver "Tratamento de áudio por classe" abaixo).

**Passos 3 e 4** (corte só na fala; crop vertical e overlay por classe) seguem
sem medição. Antes deles: medir 2–3 episódios com alternância real, e adotar
`word_timestamps` + os intervalos do Silero VAD, que já roda e é descartado.
Detalhes em `docs/01-arquitetura-segmentacao.md`.

**Pré-requisito:** todo segmento precisa terminar em 1920x1080, 60 fps CFR,
48 kHz, yuv420p. Divergência quebra o concat.

## Tratamento de áudio por classe — medido em 24/08/2026

`scripts/audio.sh` aplica cadeias distintas a FALA e MÚSICA e remonta.
Comparado ao `loudnorm` uniforme do `processa.sh`, no `ep00` (= `video_0`):

| Métrica | master | processa.sh | audio.sh | alvo |
|---|---|---|---|---|
| I total | −9,27 | −12,75 | **−14,02** | −14 LUFS |
| I fala | −14,97 | −15,31 | **−14,10** | −14 |
| I música | −8,83 | −12,38 | **−14,01** | −14 |
| LRA música | 9,00 | 7,20 | **8,90** | preservar |
| LRA fala | 7,80 | 6,20 | **4,40** | nivelar |
| True peak | +0,24 | −1,33 | −1,38 | ≤ −1 dBTP |

Três resultados que justificam o script:

1. **O `processa.sh` erra o alvo em 1,25 dB.** `loudnorm` de passo único é
   dinâmico e não converge. Em dois passos com `linear=true` acerta −14,02.
2. **O `processa.sh` deixa a fala 2,9 dB mais baixa que o violão** (−15,31 vs
   −12,38). Com as cadeias separadas a diferença cai para 0,09 dB. Esse é o
   ganho prático maior: o master tem a fala 6 dB abaixo da música, e um
   normalizador único não tem como corrigir isso.
3. **O achatamento do violão, medido.** Ganho instantâneo aplicado à região
   MÚSICA, em janelas de 500 ms: o `processa.sh` varia **9,09 dB**
   (−4,90 a +4,19, σ 1,71 dB); o `audio.sh` varia **0,08 dB** (σ 0,01 dB).
   O `loudnorm` uniforme literalmente anda em cima do violão 9 dB. Confirmado
   por outro caminho: removendo um ganho constante do resultado, sobra 40,8 dB
   de fidelidade no `audio.sh` (é o master vezes uma constante) contra 0,9 dB
   no `processa.sh` (não é).

### Decisões de implementação, todas medidas

- **A fonte é o master, não o `_norm.mp4`.** O `_norm` já levou um `loudnorm`
  dinâmico que achatou o violão; reprocessar em cima mediria o tratamento sobre
  áudio já estragado. O vídeo vem do `_norm` por cópia de stream — verificado:
  MD5 do stream de vídeo idêntico, 11377 frames nos dois.
- **Alinhamento explícito.** Os streams de áudio do master e do `_norm` começam
  em `start_time` diferentes (0,048896 s vs 0,027000 s) e o WAV descarta esse
  offset ao ser escrito. Correlação cruzada mediu 21,33 ms de defasagem — exatos
  1024 samples a 48 kHz, o atraso do codificador AAC. O `audio.sh` mede e corrige
  a cada execução; verificado depois: 0 amostras de lag.
- **Latência do `afftdn`: 25,00 ms (1200 amostras)**, medida com impulso.
  `highpass`, `acompressor` e `loudnorm` são de latência zero. Sem compensar, a
  cadeia de fala sairia 25 ms atrasada em relação à de música.
- **Máscara com rampa, não concat.** As duas cadeias rodam sobre o áudio inteiro
  em paralelo e são misturadas por uma máscara trapezoidal de 50 ms. Verificado
  com sinal DC: as duas máscaras somam **1,000000 em todas as amostras**, e
  reconstruindo ruído branco o erro é de 0,0 LSB. Não há clique nem buraco na
  emenda, e nada muda de duração.
- **`linear=true` funciona na música, não na fala.** A música precisa de
  −5,17 dB, cabe no teto de true peak, e sai como ganho estático. A fala precisa
  de +7,00 dB, o que levaria o pico a +2,69 dBTP; o `loudnorm` volta ao modo
  dinâmico. Para fala isso é o comportamento desejável, mas é bom saber que a
  flag é inócua ali.
- **`apad` antes do `-shortest`.** Sem ele o `-shortest` apara o *vídeo*, não o
  áudio: mediu-se 11376 frames contra os 11377 do `_norm`.
- O ffmpeg avisa `Invalid value NaN for volume` uma vez por ramo. É o frame de
  flush do EOF, sem `pts`. Inofensivo — provado pelo teste de DC acima.

### O que NÃO melhorou

Transcrever o áudio tratado deu resultado **ligeiramente pior** que transcrever o
`_norm`: 92,5% de similaridade de palavras, com três trechos degradados
(`microfonezinhos, olha` → `microfones e nos olhos`) e nenhum melhorado.
Provável efeito do `afftdn` sobre as consoantes. **Consequência prática:
transcrever sempre do `_norm`, nunca do `_audio`** — que é o que o fluxo já faz.

## Pendências conhecidas

- [x] ~~Áudio saindo a 96 kHz~~ — resolvido com `-ar 48000` na saída de áudio de
      `processa.sh` e `corta.sh`. O `_norm.mp4` antigo (gravado antes da correção)
      ainda está a 96 kHz; reprocessar se for publicar.
- [x] ~~`corta.sh` nunca foi executado~~ — validado em 24/08/2026 no
      `20260824_135542_norm.mp4` com dois trechos. Resultados: duração exata
      (8s + 14s = 22,000s, 1320 frames a 60 fps), PTS de vídeo e áudio contínuos,
      I-frame na emenda (o x264 detecta a troca de cena e força IDR), nenhum frame
      preto, nenhum transiente de áudio no ponto de emenda (pico desce
      −19,0 → −21,3 → −21,9 dBFS), sem erro de decodificação. Emenda seca, sem
      ghosting. Reencode de 22s levou 20s.
- [x] ~~`LD_LIBRARY_PATH` não permanente~~ — agora em `scripts/transcreve.sh`, que
      exporta a variável antes de o interpretador subir e faz `exec` no
      `transcreve.py`. O truque de `os.execv` foi removido; o Python só avisa se for
      chamado direto sem as libs no caminho.
- [x] ~~Marcar idioma do áudio~~ — `-metadata:s:a:0 language=por` agora está em
      `processa.sh`, `corta.sh` e `audio.sh`. Verificado no `ep00_audio.mp4`:
      `TAG:language=por`. O `ep00_norm.mp4` desta execução ainda saiu como `eng`
      porque foi gerado antes da correção; reprocessar se for publicar.
- [ ] Glossário de correção de transcrição ainda não existe.
- [ ] `processa.sh` continua aplicando `loudnorm` uniforme. Agora que o
      `audio.sh` existe e está medido, decidir: ou o `processa.sh` para de
      normalizar áudio (vira só vídeo + wav) e o `audio.sh` passa a ser
      obrigatório, ou os dois convivem e o `_norm` é só um rascunho. Hoje
      convivem, e o `_norm` gasta um encode de áudio que é jogado fora.
- [ ] Medir a segmentação em episódios com alternância fala/música real. Os dois
      episódios medidos até agora são o mesmo arquivo, com uma fronteira só.
      `inbox/improviso_2.mp4` (289s) ainda não foi processado.
- [ ] Os parâmetros das cadeias do `audio.sh` (`afftdn=nr=10:nf=-30`,
      `acompressor` em −18 dB / 3:1) foram escolhidos por convenção, não medidos.
      A degradação da transcrição no áudio tratado sugere que o denoise está
      forte demais. Medir antes de confiar.

## Glossário de transcrição (em construção)

O Whisper erra vocabulário técnico. Termos a vigiar e corrigir:

- dominante secundária, empréstimo modal, tétrade, cadência de engano
- rearmonização, II-V-I, grau, campo harmônico, modo mixolídio
- Erros já observados: `Falta da YouTube` (small) e `Falta nada do YouTube`
  (large-v3) → "Fala, galera do YouTube". **O large-v3 não corrige este erro** —
  trocar de modelo não substitui o glossário.
- `microfonezinhos` vira `microfones e nos olhos` quando o áudio passa pelo
  denoise do `audio.sh`.

## Ao trabalhar neste projeto

- **Medir antes de otimizar.** Todas as decisões acima vieram de números, não de intuição.
  Sugestões novas devem vir com forma de medir.
- **Não sugerir subir mídia** para nenhum serviço ou para o chat.
- **Disco é o recurso apertado.** ~31 GB livres. Um episódio de 20 min em 4K60 dá ~7 GB de
  master. Limpar `work/` após aprovar, arquivar masters após publicar.
- **Fase 0 é publicar, não perfeição.** Se algo estiver bloqueando por mais de uma
  tentativa, usar o caminho lento e seguir (ex: CPU em vez de GPU).