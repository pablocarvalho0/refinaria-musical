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
├── work/       # intermediários, .wav e .words.tsv. Descartável.
├── out/        # _norm.mp4 (trabalho: video pronto, audio cru),
│            # _audio.mp4 e _final.mp4 (entregaveis),
│            # .txt, .segments.tsv, .segmentos.txt, .srt, .ass
├── scripts/    # versionado
├── docs/       # registro das decisões de arquitetura. Versionado.
├── importado/  # codigo de terceiros EM VALIDACAO. Fora do fluxo oficial.
├── models/     # modelos Whisper baixados. Descartável (redownload).
└── .venv/      # ignorado pelo git
```

`inbox`, `work`, `out`, `models` e `.venv` estão no `.gitignore`.
**Nunca versionar mídia nem pesos de modelo.**

Os textos derivados da transcrição (`.txt`, `.segments.tsv`, `.segmentos.txt`,
`.srt`, `.ass`) ficam em `out/`, não em `work/`: são a fonte da verdade do
episódio, custam alguns KB, e `work/` existe para ser apagado sem pensar.

## Fluxo

**Cada script tem uma responsabilidade só.** O `processa.sh` cuida do vídeo,
o `audio.sh` cuida do áudio, e eles não se sobrepõem. O `_norm.mp4` é arquivo
de trabalho — vídeo pronto, áudio ainda cru. O entregável é o `_audio.mp4`.

```bash
cd ~/video && source .venv/bin/activate

# 1. Vídeo: 4K HEVC -> 1080p60 H.264. O áudio é copiado, não tratado.
#    Também extrai o .wav de 16 kHz para a transcrição.
./scripts/processa.sh ~/video/inbox/<arquivo>.mp4

# 2. Transcreve (GPU). SEMPRE do .wav do _norm, nunca do áudio tratado.
#    --word-timestamps grava o sidecar .words.tsv, insumo da legenda.
./scripts/transcreve.sh ~/video/work/<arquivo>.wav --model large-v3 --word-timestamps

# 3. Classifica fala/música e mede a zona cinzenta
python scripts/segmenta.py ~/video/work/<arquivo>.wav   # -> work/segmentos.txt

# 4. Áudio. Se a zona cinzenta passar de 10%, use --uniforme.
./scripts/audio.sh ~/video/out/<arquivo>_norm.mp4              # por classe
./scripts/audio.sh ~/video/out/<arquivo>_norm.mp4 --uniforme   # classe única

# 5. Legenda: reagrupa as palavras em cues e aplica o glossário.
#    Sai .srt (YouTube, sobe separado) e .ass (queima no vertical).
python scripts/legenda.py ~/video/work/<arquivo>.words.tsv \
    --segmentos ~/video/out/<arquivo>.segmentos.txt

# 6. Humano cola a transcrição no chat -> recebe cortes.txt e as
#    correções de texto novas (que viram linhas do glossario.tsv)

# 7. Aplica os cortes ao entregável
./scripts/corta.sh ~/video/out/<arquivo>_audio.mp4 ~/video/work/cortes.txt

# Queimar a legenda (só no vertical; no YouTube o .srt sobe separado):
ffmpeg -i <entrada>.mp4 -vf "ass=out/<arquivo>.ass" \
    -c:v libx264 -crf 20 -preset fast -pix_fmt yuv420p -r 60 \
    -c:a copy -metadata:s:a:0 language=por <saida>.mp4

# Medir loudness de qualquer arquivo, separando fala de música:
./scripts/mede-audio.sh <arquivo> ~/video/work/segmentos.txt
```

### Quem faz o quê — combinado em 30/08/2026

O fluxo tem três atores e a fronteira entre eles é o que decide o custo:

1. **Os scripts produzem o bruto.** Determinístico, roda sem supervisão,
   não consome limite de uso: vídeo, áudio, transcrição, segmentação,
   montagem dos cues e as correções que já estão no `glossario.tsv`.
2. **O Claude passa por cima do bruto.** Só o que exige julgamento: ler a
   transcrição procurando incoerência, escolher os cortes, escrever
   título e descrição. As correções de texto que ele achar **voltam como
   linhas do `glossario.tsv`**, não como um arquivo reescrito à mão.
3. **O humano valida no fim.** Assiste e aprova, ou devolve o ajuste.

Duas regras que sustentam isso:

**O Claude nunca edita timestamp.** Ele devolve pares `errado → certo`; a
reaplicação é do `legenda.py`, que recalcula os tempos. Timestamp que passa
por LLM é timestamp que ninguém conferiu.

**Erro visto duas vezes vira regra.** A primeira ocorrência custa uma
leitura do Claude; da segunda em diante é o `glossario.tsv` que resolve, de
graça e sempre igual. É o princípio 3 aplicado à revisão de texto: o
julgamento acontece uma vez e depois virou código.

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

### processa.sh não trata áudio (v3)

Até a v2 o `processa.sh` aplicava `loudnorm` de passo único ao arquivo inteiro,
e o `audio.sh` jogava esse resultado fora e refazia a partir do master. Três
custos, todos medidos:

1. **Dois entregáveis quase idênticos** em `out/`, mesma imagem, áudio diferente.
   Publicar o errado é silencioso — só se percebe ouvindo.
2. **A transcrição saía 27 ms adiantada** em relação ao vídeo. O stream de áudio
   não começa em zero (0,048896 s no ep00) e o WAV não guarda esse offset: ao
   escrever o arquivo o ffmpeg o descarta. Todo ponto de corte herdava o viés.
3. **A defasagem de 21,33 ms** que o `audio.sh` corrigia por correlação cruzada
   existia só porque o `.wav` vinha de um áudio reencodado.

Na v3 o `processa.sh` usa `-c:a copy` e extrai o `.wav` com `first_pts=0`.
O áudio do `_norm` passa a ser **bit-idêntico ao do master** (MD5 conferido) e
os itens 2 e 3 somem por construção, em vez de serem corrigidos a cada execução.
O `audio.sh` virou o único produtor de áudio, e ganhou um modo `--uniforme` para
o episódio cuja zona cinzenta estoure o critério.

Efeitos colaterais medidos, todos a favor:

| | v2 | v3 |
|---|---|---|
| `processa.sh` | 2m27,9s | **2m15,4s** (sai o encode de AAC) |
| Gerações de AAC no entregável | 2 | **1** |
| Bitrate do áudio de trabalho | 192k reencodado | **256k do celular, intacto** |
| Zona cinzenta | 3,2% | **1,7%** |
| Ambiguidade na fronteira | 5,00s | **1,99s** |
| Alternância mínima tolerada | ~50s | **~20s** |

As duas últimas linhas foram surpresa. Transcrever do áudio cru move a fronteira
FALA→MUSICA de 34,600s para 37,610s — mais perto de onde a energia realmente
assenta. O `loudnorm` dinâmico do `_norm` estava empurrando o VAD para cortar
cedo demais.

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
- `docs/02-import-video-use.md` — **import em andamento** do
  `browser-use/video-use` (MIT). Decisão de 30/08/2026: importar peça por
  peça, em `importado/`, com validação medida antes de qualquer coisa
  migrar para `scripts/`. Ler antes de mexer em `importado/`.

## Segmentação fala/música (Fase 1 — passo 2 feito)

A transcrição particiona o vídeo em duas classes: onde há texto é FALA, onde
não há é MÚSICA. Cada classe recebe cadeia de processamento própria, e os
segmentos são reunidos ao final.

Supera a regra defensiva anterior ("a transcrição diz onde não cortar").

**Passo 1 — medir a zona cinzenta.** `scripts/segmenta.py`. Medido quatro vezes
no mesmo episódio (`video_0`, 189,6s):

| Transcrição de | Modelo | Regra de fusão | Zona cinzenta | Ambiguidade |
|---|---|---|---|---|
| `_norm` (loudnorm) | `small` | não | 3,0% | 4,46s |
| `_norm` (loudnorm) | `large-v3` | não | 3,2% | 5,00s |
| áudio cru | `large-v3` | não | 7,2% | 5,77s |
| **áudio cru** | **`large-v3`** | **sim** | **1,7%** | **1,99s** |
| áudio cru + `--word-timestamps` | `large-v3` | sim | 2,1% | 2,19s |

Duas lições. **Trocar de modelo não ajuda**: o `large-v3` piorou a fronteira em
relação ao `small`. **O que ajuda é não normalizar antes de transcrever** — o
`loudnorm` dinâmico empurrava o VAD a cortar a fala 3s cedo demais.

A última linha é de 30/08/2026 e piora de propósito. Com `--word-timestamps`
o Whisper aperta as fronteiras do segmento contra as palavras — a fala passa
a começar em 1,790s em vez de 1,170s e a terminar em 37,410s em vez de
37,610s. O trecho de música que sobra no começo é curto demais e cai na zona
cinzenta, daí os 0,4 pontos a mais. Continua muito abaixo do critério de 10%,
e as fronteiras novas são as corretas: são as que o alinhamento por palavra
mediu. **O `segmentos.txt` de um episódio tem que ser gerado da mesma
transcrição que gerou a legenda**, senão os dois discordam por ~200 ms.

A "regra de desempate simples" que este documento previu virou código: fundir
regiões de fala separadas por menos de 2s. Sem ela o áudio cru fica pior (7,2%),
porque o Whisper abre um buraco de 1s no meio de uma fala corrida e isso cria
duas fronteiras falsas.

O custo é **por fronteira, não por minuto**. A regra derivada, com os números
novos: a segmentação só por transcrição se sustenta enquanto a alternância
fala/música for **mais espaçada que ~20s** (era ~50s). Este episódio tem **uma
única fronteira medível** e é o caso favorável extremo. n=1 — a medição autoriza
o passo 2, não a generalização.

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

| Métrica | master (= `_norm` v3) | `processa.sh` v2 | `audio.sh` | `--uniforme` | alvo |
|---|---|---|---|---|---|
| I total | −9,27 | −12,75 | **−14,01** | −14,02 | −14 LUFS |
| I fala | −14,67 | −15,31 | **−14,20** | −19,38 | −14 |
| I música | −8,83 | −12,38 | **−14,01** | −13,55 | −14 |
| LRA música | 8,60 | 7,20 | **8,50** | 8,60 | preservar |
| LRA fala | 7,80 | 6,20 | **4,70** | 7,80 | nivelar |
| True peak | +0,24 | −1,33 | −1,35 | −4,48 | ≤ −1 dBTP |

O modo `--uniforme` acerta o alvo e **não achata** (LRA total 10,70, idêntico à
fonte), mas não corrige o desequilíbrio: deixa a fala 5,8 dB abaixo da música.
É a rede de segurança, não o caminho bom.

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

## Legendas — medido em 30/08/2026

`scripts/legenda.py` transforma o sidecar de palavras em `.srt` e `.ass`.

**Por que não usar os segmentos do Whisper.** No `ep00` o primeiro segmento
tem **29,00s e 427 caracteres** (14,7 char/s); o segundo, 6,44s e 65. Isso é
parágrafo, não legenda. A norma de leitura é duas linhas de ~42 caracteres,
1 a 6 segundos em tela. O dado que resolve já existia e estava sendo jogado
fora: `--word-timestamps` era aceito pelo `transcreve.py`, mas `seg.words`
não era gravado.

Com as 88 palavras alinhadas, o resultado no `ep00`: **9 cues**, de 1,20 a
4,90s (média 3,58), 5 a 78 caracteres (média 52), 4,2 a 17,0 char/s.

**Regras de fecho de cue**, todas no topo do script para serem ajustadas
depois de ver na tela: pontuação forte fecha sempre; vírgula fecha se o cue
já tem 60% do teto; pausa entre palavras acima de 0,7s fecha; teto de 84
caracteres ou 5s fecha. Depois o script dá 0,2s de folga, garante 1,2s
mínimo e nunca invade o cue seguinte.

**Cue rápido demais estica.** A abertura saía a 17,7 char/s. Como havia
folga até o cue seguinte, usá-la não custa nada — o texto não muda, só fica
mais tempo legível. Máximo do episódio caiu para 17,0 char/s.

**A legenda passa pelo filtro de FALA.** As palavras são cruzadas com as
regiões do `segmentos.txt`; o que cai fora é descartado. No `ep00` foram 0
descartes, mas 152 dos 189 segundos são violão solo — é exatamente onde o
Whisper alucina, e essa é a rede.

**Destino diferente por plataforma.** No YouTube o `.srt` sobe separado:
zero reencode, o espectador liga e desliga, e a plataforma indexa o texto.
No vertical a legenda é queimada com o filtro `ass` — o corte vertical já
reencoda, então não custa geração extra. Ambiente já tem tudo: ffmpeg com
`libass`, `libfreetype`, `libfontconfig`, `libharfbuzz` e 1023 fontes.

Estilo atual: Inter Bold 54px em `PlayResY=1080`, contorno preto 3,2,
sombra 1,0, margem inferior 90. Validado na tela sobre fundo claro e escuro.

**A probabilidade por palavra aponta onde olhar, não o que corrigir.**
Média das 88 palavras: 0,864. Nas quatro do bordão errado: 0,577 (`do` em
0,366). Mas das 11 palavras abaixo de 0,60, só 3 estavam no erro real —
`tô`, `posso` e `isso` são fala rápida correta. Precisão de 27%, e `nada`
escapou com 0,907. Serve para priorizar a leitura, não para decidir sozinha.
Quem decide é a leitura do texto.

**O que a leitura pega e a probabilidade não.** No `ep00` a frase "eu vou
pretender editar" saiu com 0,938 de confiança — o modelo estava seguro do
som. A construção é que é estranha em português. Conferido com o autor:
**ele falou assim mesmo**, e ficou como está. Fala espontânea não se
corrige; legenda transcreve o que foi dito.

## O corte que derrubava a IDE — 30/08/2026

Em 30/08/2026 o `corta.sh` fechou a Antigravity três vezes: 10:57, 13:37 e
13:42. O sintoma era a IDE simplesmente sumindo no meio do trabalho, sem
diálogo de erro e sem log dela própria. Fica registrado porque o sintoma
apontava para o lugar errado — a IDE não tinha culpa nenhuma.

**A IDE morria porque o ffmpeg morria.** Tudo que a IDE abre, inclusive o
terminal e os processos disparados nele, vive no mesmo scope do systemd
(`app-org.chromium.Chromium-<pid>.scope`), e esse scope tem
`OOMPolicy=stop`: basta UM processo lá dentro ser morto pelo OOM killer
para o systemd derrubar o scope inteiro. Os três scopes com
`Result=oom-kill` batem no segundo com os três `Out of memory: Killed
process ... (ffmpeg)` do kernel — 11,3 GB, 12,1 GB e 12,5 GB de RSS numa
máquina de 15 GB.

**Rodar no terminal comum não resolveria.** O OOM era global
(`constraint=CONSTRAINT_NONE`), não um limite de cgroup. O ffmpeg seria
morto em qualquer lugar; só mudaria a vítima colateral, porque o scope do
terminal do GNOME também tem `OOMPolicy=stop`. O corte continuaria
falhando.

**A causa era o formato do grafo de filtros, não o tamanho do arquivo.**
A versão anterior do `corta.sh` usava um único `-i` e derivava um ramo
`[0:v]trim=start=..:end=..` por trecho. Reusar a mesma entrada em vários
ramos faz o ffmpeg inserir um `split` implícito, e o `split` precisa
entregar cada frame decodificado a **todos** os ramos ao mesmo tempo — os
que o `concat` ainda não está consumindo acumulam na fila do filtro. Em
1080p60 yuv420p cada frame decodificado ocupa 3,1 MB, então alguns
milhares enfileirados passam de 10 GB. O vídeo do episódio tinha 5
minutos e 170 MB.

**A correção é uma entrada por trecho.** Com `-ss`/`-to` antes de cada
`-i` o ffmpeg busca direto no ponto e decodifica só o necessário: não há
`split`, não há fila. O `-ss` como opção de entrada não custa precisão —
com reencode o ffmpeg faz accurate seek por padrão, e o ponto de corte
continua caindo na fronteira de palavra que o `words.tsv` apontou.

Medido no mesmo corte do `improviso_2`, com o mesmo `cortes.txt` de 4
trechos:

| | antes (`trim` + `split`) | depois (`-ss`/`-to` por entrada) |
|---|---|---|
| pico de RSS | 12,5 GB | 1,20 GB, estável |
| desfecho | OOM, IDE fechada | código 0 |
| duração da saída | — (truncada em 8,1 MB) | 186,95 s |

Os 186,95 s conferem com os 186,91 s da soma dos trechos; a diferença de
40 ms é arredondamento de frame, o mesmo comportamento da versão antiga.

**O ffmpeg pesado agora roda num cgroup próprio.** O `scripts/lib.sh`
traz a função `ffmpeg_lim`, usada pelo `corta.sh`, pelo `processa.sh` e
pelo render do `audio.sh`. Ela envolve o ffmpeg num `systemd-run --scope`
com `MemoryMax=6G` e `MemorySwapMax=0`. Se estourar, morre só o encode,
com mensagem legível, e quem chamou continua de pé:

```bash
MEM_MAX=10G ./scripts/corta.sh ...   # para dar mais folga
SEM_LIMITE=1 ./scripts/corta.sh ...  # para desligar a proteção
```

O `MemorySwapMax=0` não é detalhe: sem ele a máquina passa minutos
swapando, com o desktop travado, antes de alguém morrer. Com ele a falha
é rápida e legível. Sem systemd de usuário (container, ssh sem sessão) a
função cai no ffmpeg puro com um aviso — perde a rede, não impede o
trabalho.

**A lição que generaliza.** Um processo pesado disparado do terminal da
IDE compartilha o destino da IDE. Quando algo "fecha sozinho" durante um
trabalho pesado, o primeiro lugar a olhar é
`journalctl --since today | grep -i oom`, não o log da aplicação.

## Import do browser-use/video-use — em validação

Desde 30/08/2026 há uma importação parcial e sob teste do
[browser-use/video-use](https://github.com/browser-use/video-use) (MIT), que
chegou à mesma tese central deste projeto por conta própria. **Nada de
`importado/` faz parte do fluxo acima.** O registro completo — o que entrou,
a fila, o que foi recusado e por quê — está em `docs/02-import-video-use.md`.

Duas regras enquanto o import estiver aberto:

- **`importado/` não é chamado por `scripts/`.** Um item só migra quando o
  critério de validação dele estiver cumprido e medido no documento.
- **O `SKILL.md` deles não é registrado como skill.** As 12 regras duras
  dele conflitam com este arquivo (exige ASR da ElevenLabs, manda cortar em
  silêncios ≥400 ms, impõe outra estrutura de diretórios). As ideias boas
  entram como texto no documento, não como skill carregada em contexto.

Primeiro item portado: `importado/video-use/timeline.py`, que condensa um
intervalo do vídeo numa PNG (frames + forma de onda + palavras + classes).
Ele já rendeu um achado: os **quatro** gaps de silêncio ≥0,4s da região de
fala do `ep00` estão todos musicalmente ocupados (−5,9 a −15,8 dB relativos
ao pico). A heurística de corte por silêncio do video-use teria gerado 4
candidatos, todos errados — n=4, 100% de falso positivo. É a confirmação
mais direta que temos da remoção do auto-editor.

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
- [x] ~~Marcar idioma do áudio~~ — `-metadata:s:a:0 language=por` está em
      `processa.sh`, `corta.sh` e `audio.sh`. Verificado no `ep00_audio.mp4`.
- [x] ~~Glossário de correção de transcrição ainda não existe~~ — agora é
      `scripts/glossario.tsv`, aplicado pelo `legenda.py` sobre a sequência
      de palavras **antes** da montagem dos cues, para que a pontuação
      corrigida influencie onde a legenda quebra. Casa por sequência
      ignorando caixa e pontuação, preserva a pontuação final do original e
      redistribui os timestamps dentro da mesma janela de tempo. Cada troca
      é impressa na execução. Começou com 4 regras.
- [x] ~~`processa.sh` aplicando `loudnorm` uniforme~~ — resolvido na v3: ele não
      toca mais no áudio, e o `audio.sh` virou o único produtor. Ver a decisão
      "processa.sh não trata áudio (v3)" acima.
- [ ] Medir a segmentação em episódios com alternância fala/música real. Os dois
      episódios medidos até agora são o mesmo arquivo, com uma fronteira só.
      `inbox/improviso_2.mp4` (289s) ainda não foi processado.
- [ ] **Import video-use, item 1** — validar o `timeline.py` num episódio com
      pausa seca de verdade. O limiar de −25 dB da guarda de energia só foi
      calibrado pelo lado da rejeição; nunca disparou positivo, porque no
      `ep00` não existe silêncio real. Ver `docs/02-import-video-use.md`.
- [ ] **Import video-use, item 2** — auto-avaliação do render: rodar o
      `timeline.py` no arquivo cortado, em cada emenda, procurando salto
      visual, pico de onda e legenda coberta.
- [ ] **Import video-use, item 4** — medir a margem da legenda no vertical
      dentro do app. Eles põem a legenda a ~31% da altura alegando que a UI
      de Reels/Shorts cobre os 25–30% inferiores; a nossa está a 8,3%. É o
      único item do import que afeta o que já está pronto para publicar.
- [ ] Os parâmetros das cadeias do `audio.sh` (`afftdn=nr=10:nf=-30`,
      `acompressor` em −18 dB / 3:1) foram escolhidos por convenção, não medidos.
      A degradação da transcrição no áudio tratado sugere que o denoise está
      forte demais. Medir antes de confiar.

## Glossário de transcrição

As regras aplicadas automaticamente vivem em **`scripts/glossario.tsv`**.
Só entra ali o que foi ouvido e confirmado — palpite fica no relatório de
trechos duvidosos, não no arquivo que roda sem supervisão.

O Whisper erra vocabulário técnico. Termos a vigiar e corrigir:

- dominante secundária, empréstimo modal, tétrade, cadência de engano
- rearmonização, II-V-I, grau, campo harmônico, modo mixolídio
- Erros já observados: `Falta da YouTube` (small) e `Falta nada do YouTube`
  (large-v3) → "Fala, galera do YouTube". **O large-v3 não corrige este erro** —
  trocar de modelo não substitui o glossário. Está no `glossario.tsv` desde
  30/08/2026 e o `legenda.py` corrige sozinho.
- `microfonezinhos` vira `microfones e nos olhos` quando o áudio passa pelo
  denoise do `audio.sh`.

## Ao trabalhar neste projeto

- **Medir antes de otimizar.** Todas as decisões acima vieram de números, não de intuição.
  Sugestões novas devem vir com forma de medir.
- **Não sugerir subir mídia** para nenhum serviço ou para o chat.
- **Disco é o recurso apertado.** ~25 GB livres em 30/08/2026. Um episódio de 20 min em 4K60 dá ~7 GB de
  master. Limpar `work/` após aprovar, arquivar masters após publicar.
- **Fase 0 é publicar, não perfeição.** Se algo estiver bloqueando por mais de uma
  tentativa, usar o caminho lento e seguir (ex: CPU em vez de GPU).
- **Se a IDE ou o terminal fechar sozinho durante um trabalho pesado, é OOM até prova
  em contrário.** Olhar `journalctl --since today | grep -i oom` antes do log da
  aplicação. Processo pesado disparado do terminal da IDE compartilha o cgroup — e o
  destino — dela. Ver "O corte que derrubava a IDE".
- **ffmpeg novo passa pelo `ffmpeg_lim` do `scripts/lib.sh`**, não pelo `ffmpeg` direto,
  sempre que processar arquivo inteiro. E desconfiar de grafo que reusa a mesma entrada
  em vários ramos: é o padrão que enfileira frames decodificados até estourar.