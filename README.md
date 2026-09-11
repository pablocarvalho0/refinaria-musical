# Refinaria musical — pipeline de vídeo

Produção de vídeo de violão para YouTube e Instagram, do celular ao ar. Roda
inteiramente local: nenhum arquivo de mídia sai da máquina.

O repositório versiona a receita — scripts, tokens de identidade visual e o
registro das decisões. Mídia, modelos e credenciais ficam de fora.

## A ideia central

Vídeo é caro de processar e opaco para automatizar. Texto não é.

O áudio vira transcrição com timestamps logo no início, e daí em diante corte,
capítulo, legenda, descrição e carrossel são derivados do mesmo arquivo de
texto. O vídeo só é tocado quando não há alternativa.

Quatro princípios governam o resto, e cada decisão registrada em `docs/` sai de
um deles:

1. **A transcrição é a fonte da verdade.** Erro nela contamina tudo a jusante.
   Em episódio instrumental, onde o Whisper devolve zero palavras, o relógio
   equivalente é a grade musical (`grade-musical.py`).
2. **Bits pesados nunca sobem para o chat.** O `.mp4` fica na máquina; para o
   Claude vai texto e, no máximo, um frame PNG.
3. **Script escrito uma vez roda para sempre.** Tarefa determinística vira
   código. Só volta ao julgamento humano o que exige julgamento.
4. **Medir antes de otimizar.** Nenhum número neste repositório foi estimado.

## O que o pipeline faz hoje

| Etapa | Script | Estado |
|---|---|---|
| Sonda a geometria do que chegou | `sonda.sh` | em uso |
| Normaliza o vídeo (horizontal ou vertical) | `processa.sh` | em uso |
| Transcreve na GPU, com alinhamento por palavra | `transcreve.sh` | em uso |
| Classifica FALA/MÚSICA | `segmenta.py` | em uso |
| Trata o áudio por classe | `audio.sh` | em uso |
| Trata violão solo (reverb, ganho lento) | `violao.sh` | em uso |
| Monta legendas `.srt` e `.ass` por formato | `legenda.py` | em uso |
| Mede se a legenda é legível sobre o vídeo real | `valida-legenda.py` | em uso |
| Aplica os cortes escolhidos | `corta.sh` | em uso |
| Vertical a partir de master horizontal | `vertical.sh` | em uso |
| Câmera virtual sobre plano fixo | `dinamica.sh` | em uso |
| Cartelas de abertura e créditos | `cartelas.py`, `monta-cartelas.sh` | em uso |
| Artes de marca, capa e carrossel | `marca.py`, `capa.py`, `carrossel.py` | em uso |
| Grade rítmica e fronteiras de seção | `grade-musical.py`, `secoes.py` | em uso |
| Sobe, escreve metadado e publica no YouTube | `youtube.py` | em uso |
| Sincroniza gravações separadas da mesma música | `alinha-faixas.py` | fora do fluxo |

O Instagram é manual de propósito: não há API que resolva o que interessa lá
(capa de Reel, colaboradores).

## Requisitos

- Ubuntu 24.04, ffmpeg 6.1 com `libass` e NVENC, Python 3.12
- GPU NVIDIA para a transcrição e para decodificar 4K/8K HEVC. Há queda para
  CPU, muito mais lenta
- Fontes da identidade visual: Inter, Bitstream Charter e EB Garamond
- Syncthing, só para a ingestão — qualquer forma de pôr um `.mp4` na `inbox`
  serve

## Instalação

```bash
sudo apt install ffmpeg mpv fonts-inter xfonts-scalable fonts-ebgaramond-extra

git clone https://github.com/pablocarvalho0/refinaria-musical.git ~/video && cd ~/video
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

mkdir -p inbox work out models
```

Duas regras de ambiente que já custaram tempo:

- **Sempre ativar o venv antes de rodar Python.** Não usar `mise` neste
  projeto: o `mise.toml` desativa o venv e produz `ModuleNotFoundError`.
- **As libs CUDA precisam estar no `LD_LIBRARY_PATH` antes de o interpretador
  subir.** O CTranslate2 as carrega preguiçosamente, então a falha só aparece
  na primeira inferência. Por isso a transcrição tem um wrapper em shell
  (`transcreve.sh`) — chamar o `.py` direto é o caminho errado.

Os modelos Whisper ficam em `models/`, fora do git. O download pelo
`huggingface_hub` travou duas vezes na metade do `large-v3`; `curl -L -C -`
retomou e completou cinco vezes mais rápido.

## Ingestão

O contrato é simples: **ponha um `.mp4` em `~/video/inbox` e rode o
`processa.sh`**. Cabo, `adb pull`, `scp`, cartão SD — tanto faz.

O que uso é Syncthing, com o celular em **Send Only** e o Ubuntu em **Receive
Only**, apontado para `~/video/inbox` e nunca para `~/video`: sincronizar a
raiz colocaria o `.git` dentro da pasta compartilhada, e o celular em Send Only
teria licença para apagar objetos do repositório. Master se regrava,
transcrição se refaz — o histórico do projeto é a única coisa aqui que não dá
para recriar.

No Android o app é o **Syncthing-Fork** (o oficial foi descontinuado em
dezembro de 2024).

## Gravação

| Ajuste | Valor | Por quê |
|---|---|---|
| Resolução | a maior disponível | a resolução de entrega se decide pela fonte; ver abaixo |
| Taxa | 60 fps | palhetada e dedilhado ficam legíveis |
| Codec | HEVC | a GPU decodifica |
| HDR10+ | desligado | cor lavada depois de transcodificar |
| Estabilização | desligada | com tripé, só introduz artefato |
| Enquadramento automático | desligado | corta o braço do violão |

Horizontal e vertical convivem: o `processa.sh` lê o side data `rotation` e
escolhe 1920x1080 ou 1080x1920 sozinho. `ORIENTACAO=h|v` força, para quando o
metadado mentir.

Três hábitos de gravação convertem trabalho de edição em metadado legível por
script:

- **Falar o nome do acorde em voz alta** — a narração carimba o timestamp.
- **Bater palma antes de refazer um take** — pico isolado, trivial de achar.
- **Falar antes e depois de tocar** — delimita a região musical no texto.

## O fluxo de um episódio

`<ep>` é o nome do episódio, e é ele que dá nome à pasta de saída. Nenhum
comando diz onde escrever: os scripts resolvem `out/<ep>/` sozinhos e imprimem
o que resolveram antes de escrever.

```bash
cd ~/video && source .venv/bin/activate

# 0. Geometria do que chegou — vertical e horizontal convivem
./scripts/sonda.sh

# 1. Vídeo: 4K/8K HEVC -> 1080p60 H.264 na orientação certa.
#    O áudio é COPIADO, não tratado. Sai também o .wav de 16 kHz.
./scripts/processa.sh ~/video/inbox/<ep>.mp4

# 2. Transcrição na GPU, SEMPRE do .wav do _norm (áudio cru)
./scripts/transcreve.sh ~/video/work/<ep>.wav --model large-v3 --word-timestamps

# 3. Classifica fala/música e mede a zona cinzenta
python scripts/segmenta.py ~/video/work/<ep>.wav

# 4. Áudio. Se a zona cinzenta passar de 10%, use --uniforme.
./scripts/audio.sh ~/video/out/<ep>/<ep>_norm.mp4

# 5. Legendas. O .srt é único e sobe separado; o .ass sai um por formato.
python scripts/legenda.py ~/video/work/<ep>.words.tsv \
    --segmentos ~/video/out/<ep>/<ep>.segmentos.txt
python scripts/legenda.py ~/video/work/<ep>.words.tsv \
    --segmentos ~/video/out/<ep>/<ep>.segmentos.txt --formato 9x16

# 5b. Confere que a legenda é legível sobre o vídeo real, não sobre um cinza
python scripts/valida-legenda.py ~/video/out/<ep>/<ep>_audio.mp4 \
    ~/video/out/<ep>/<ep>.16x9.ass

# 6. Julgamento humano: ler a transcrição e escolher os cortes -> work/cortes.txt

# 7. Aplicar os cortes ao entregável
./scripts/corta.sh ~/video/out/<ep>/<ep>_audio.mp4 ~/video/work/cortes.txt
```

Formato do `cortes.txt` — trechos a **MANTER**, um por linha:

```
00:00:04  00:00:12
00:00:23  00:03:09
```

### Quem faz o quê

O fluxo tem três atores, e a fronteira entre eles é o que decide o custo:

- **Os scripts produzem o bruto.** Determinístico, roda sem supervisão: vídeo,
  áudio, transcrição, segmentação, cues e as correções já no `glossario.tsv`.
- **O Claude passa por cima do bruto.** Só o que exige julgamento: ler a
  transcrição procurando incoerência, escolher cortes, escrever título e
  descrição. Correção de texto que ele achar volta como **linha do
  `glossario.tsv`**, nunca como arquivo reescrito à mão — ele não edita
  timestamp, porque timestamp que passa por LLM é timestamp que ninguém
  conferiu.
- **O humano valida no fim.** Assiste e aprova, ou devolve o ajuste.

Erro visto duas vezes vira regra: a primeira ocorrência custa uma leitura, da
segunda em diante o `glossario.tsv` resolve de graça e sempre igual.

## Áudio

O `processa.sh` **não toca no áudio** — copia o stream do master, bit a bit.
Quem produz áudio é o `audio.sh`, sozinho, e ele trata FALA e MÚSICA com
cadeias distintas, misturadas por uma máscara com rampa de 50 ms (a soma das
duas máscaras é exatamente 1 em todas as amostras — medido).

```
FALA     highpass 80 Hz + compressão suave + loudnorm I=-14, dois passos
MÚSICA   loudnorm I=-14 com LRA alto — sem compressão
```

**Não há denoise em nenhuma das duas.** O `afftdn` saiu em 06/09/2026 porque
piorava a transcrição, e piorava mais justamente no material barulhento, onde
deveria ganhar (ep00: 88,2% de similaridade com denoise contra 93,3% sem;
gravação externa: 74,7% contra 91,1%). Não havia piso de ruído banda larga para
remover — o que existe é ronco, trabalho de high-pass, que já está na cadeia.

Violão solo instrumental não passa pela cadeia de MÚSICA do `audio.sh`, que é
só um loudnorm: passa pelo `violao.sh`, com reverb por convolução e **ganho
lento em vez de compressor** (mesmo nivelamento, 7,66 dB de profundidade a
menos cobrados). O resultado entra de volta como `MUSICA_WAV=`.

Para conferir qualquer arquivo, separando fala de música:

```bash
./scripts/mede-audio.sh <arquivo> ~/video/out/<ep>/<ep>.segmentos.txt
```

## Entregável vertical

Master vertical o `processa.sh` já resolve. O caso difícil é o master
horizontal que precisa virar 9:16 — e o corte central não serve quando há duas
pessoas no plano.

```bash
./scripts/vertical.sh inbox/<ep>.mp4 --sufixo v \
    --fechado 6.571 --fechado-x 5200 --geral 14.466 --topo-y 150 --base-y 600
```

O `vertical.sh` empilha dois recortes de metade da largura, um sobre o outro, e
pode abrir com plano fechado que **afasta** até o plano geral antes de dividir a
tela. Sem o plano geral antes, os dois painéis lêem como duas gravações
separadas em vez de um take só.

Para plano fixo que estaciona na tela, a alternativa é a câmera virtual:
`dinamica.sh` + `camera.py` animam zoom e reenquadramento dentro do master, e
recusam qualquer enquadramento que ampliaria.

### A resolução de entrega se decide pela fonte, não pelo formato

O teste é **"isto ainda é redução?"**, etapa por etapa. O `vertical.sh` não tem
resolução escrita: escolhe o maior degrau de `1080 1440 2160 2880 4320` que o
master sustente sem ampliar em nenhuma etapa, e imprime qual etapa o limitou.

| master | com `--fechado`? | teto | saída |
|---|---|---|---|
| 8K | sim | 2430 px (janela 9:16 mais apertada) | 2160x3840 |
| 8K | não | 3840 px | 2880x5120 |
| 4K | sim | 1215 px | 1080x1920 |
| 4K | não | 1920 px | 1440x2560 |

`RESOLUCAO=` força, e o script avisa qual etapa vai ampliar. Cartela e legenda
acompanham em pixel **nativo**, nunca escaladas — cartela gerada em 1080 e
esticada para 4K entra com texto borrado, e aí o ganho some justamente na parte
do quadro que é tipografia pura.

## Identidade visual

`marca/tokens.toml` é a fonte da verdade do visual, e os scripts o **lêem**.
Não existe manual de marca aqui: um manual é consultado duas vezes e esquecido,
o que sobrevive a 47 episódios é o valor que o script aplica sozinho. Mudar a
cor de acento no `.toml` muda logo, capa, cartela, carrossel e legenda de uma
vez.

```bash
python scripts/marca.py tudo out/<ep>/<ep>_audio.mp4 --t 12 --titulo "..."
python scripts/carrossel.py out/<ep>/<ep>_audio.mp4 --t 145
python scripts/capa.py out/<ep>/<ep>_final.mp4 --trechos 0-2.7,15.4-22.5
python scripts/cartelas.sh <entrada>.mp4 --titulo "..." --autoria "..." --ano 1964
```

As peças são geradas sobre **frames reais do episódio**, não sobre fundo de
estúdio: é a única forma de ver se o texto sobrevive à parede branca estourada
e ao violão claro. Os três validadores (`valida-legenda.py`,
`valida-cartela.py`, `valida-marca.py`) renderizam com e sem o texto, usam os
pixels que mudaram como máscara e medem contraste WCAG contra o que havia por
baixo.

Duas coisas que essa medição já decidiu, e que não se reabrem sem número novo:

- **O contorno é o que sustenta a legenda.** Sem ele, 7,6% do texto no
  horizontal e até 32,4% numa gravação externa ficariam abaixo de 4,5:1. Com
  ele, o pior caso é 11,5:1 e o fundo deixa de importar.
- **Contraste ruim quase nunca se conserta clareando a letra.** Nas cartelas
  não existe faixa do quadro onde branco puro alcance 4,5:1 — procurar a faixa
  boa não é alternativa. O que falta é escurecer o fundo: scrim, não fonte mais
  clara.

## Publicação

```bash
python scripts/youtube.py autoriza                        # uma vez
python scripts/youtube.py sobe video.mp4 meta.txt         # entra PRIVADO
python scripts/youtube.py sobe video.mp4 --como-o <ID>    # copia o texto de outro
python scripts/youtube.py lista
python scripts/youtube.py aplica <ID> meta.txt --seco     # mostra sem enviar
python scripts/youtube.py capa <ID> capa.jpg
python scripts/youtube.py publica <ID> --como nao-listado
```

**Subir e publicar são ações diferentes, e só uma é irreversível.** `sobe` entra
sempre privado; mudar visibilidade é `publica`, e ir para `public` exige
`--sim`. Vídeo que ficou público por trinta segundos pode ter sido visto,
indexado e notificado a inscritos.

Três armadilhas da Data API que já morderam:

- `videos.update` **sobrescreve a parte inteira**: campo não reenviado dentro de
  `snippet` é apagado. O script lê o snippet atual, funde e só então envia.
- **"Feito para crianças" chega ligado sem avisar** e desliga comentários,
  notificação a inscritos, playlists, cards e telas finais. O script manda
  `selfDeclaredMadeForKids: False` explícito.
- **O app em modo Teste mata o token a cada 7 dias.** Publicá-lo exigiria três
  URLs públicas; para uso próprio não compensa, então reautoriza quando expirar.

O Reel do Instagram sobe na mão. O que aprendi lá: o Instagram escolhe a capa
sozinho e escolhe mal (pegou a cartela de créditos uma vez), e "Add
collaborators" é o único campo do formulário que multiplica alcance de graça.

## Episódio instrumental

Quando não há fala, a transcrição não diz nada, e o relógio é a música:

```bash
python scripts/grade-musical.py out/<ep>/<ep>_audio.mp4 --encaixa 7.0 15.0
python scripts/secoes.py out/<ep>/<ep>_audio.mp4
python scripts/harmonia.py --cues cues.tsv --prefixo work/<ep>_harm
```

O `--encaixa` é o uso prático: em vez de escolher "o corte fica em 7,0s" no
olho, ele devolve o tempo forte mais próximo com o erro em milissegundos.
Transição que cai fora da batida briga com a música; a que cai em cima some
dentro dela.

**Nada aqui adivinha acorde.** Reconhecimento automático foi descartado com
número (25 classes a ~67% de acurácia, sem sétimas nem inversões — inútil para
harmonia funcional). O autor já sabe os acordes; o que falta é o *quando*, e
isso a medição de seções entrega.

## Convenções que o pipeline impõe

**Uma pasta por episódio.** Tudo que um master gera mora em `out/<ep>/`. Quem
resolve a pasta é o script, em quatro degraus — `$PROJETO`, o caminho já sob
`out/<X>/`, a maior pasta de `out/` que prefixa o nome, e o nome limpo — e todo
script imprime `==> Projeto: <nome> (por <degrau>)` antes de escrever. A regra
está escrita duas vezes, em `lib.sh` e `projeto.py`, porque metade do pipeline é
shell; o que impede as duas de divergirem é `./scripts/testa-projeto.sh`, que
roda os dois lados sobre a mesma bateria de casos.

**Variante em julgamento mora em `out/<ep>/testes/<rodada>/`.**

```bash
RODADA=2026-09-05-dinamismo ./scripts/vertical.sh inbox/<ep>.mp4 ...
```

Uma rodada de quatro opções já pôs dez arquivos soltos na pasta do episódio, e
aí o nome do arquivo volta a ser a única coisa separando o que se publica do que
ainda se julga. Promover é `mv`, limpar é `rm -r`. O texto do episódio —
transcrição, `.srt`, `.segmentos.txt` — ignora a rodada de propósito, e os
scripts anunciam isso.

**ffmpeg pesado roda em cgroup próprio.** `ffmpeg_lim`, no `lib.sh`, envolve o
encode num `systemd-run --scope` com `MemoryMax=6G` e `MemorySwapMax=0`.

```bash
MEM_MAX=10G ./scripts/corta.sh ...    # mais folga
SEM_LIMITE=1 ./scripts/corta.sh ...   # desliga a proteção
```

Isso existe porque um ffmpeg estourando 12,5 GB derrubava a IDE inteira: tudo
que a IDE abre vive no mesmo scope do systemd, e esse scope tem
`OOMPolicy=stop`. **Se a IDE ou o terminal fechar sozinho durante trabalho
pesado, é OOM até prova em contrário** — olhar `journalctl --since today | grep
-i oom` antes do log da aplicação.

E desconfiar de grafo de filtros que reusa a mesma entrada em vários ramos: o
`split` implícito entrega cada frame a todos os ramos ao mesmo tempo, e o que o
`concat` ainda não consumiu se enfileira até estourar. Uma entrada `-ss`/`-to`
por trecho derrubou o pico de 12,5 GB para 1,20 GB.

## Desempenho medido

Fonte de 1,4 GB, 4K60 HEVC, 3min09, no hardware descrito no `CLAUDE.md`:

| Etapa | Tempo | Observação |
|---|---|---|
| `processa.sh` v3 | 2m15s | x264 crf 23 preset fast; áudio copiado |
| Transcrição `large-v3` na GPU | segundos | com `--word-timestamps` |
| `corta.sh` | ~20s para 22s de saída | pico de RSS 1,20 GB |
| `vertical.sh` empilhado, master 8K | 1m40s | três ramos, sem chegar ao teto |

x264 em vez de NVENC não é preferência: o NVENC da GTX 1650 (Turing) desperdiça
bitrate — 357 MB contra 84 MB do x264 para a mesma fonte, e `-b:v 0` não
corrigiu. A GPU continua decodificando (`-hwaccel cuda`), que é a parte cara.

## Manutenção

Disco é o recurso apertado. Um episódio de 20 min em 4K60 dá ~7 GB de master.

```bash
rm -rf out/<ep>/testes/      # a primeira coisa a apagar: variantes recusadas
rm work/<ep>*.wav            # work/ é descartável por design
du -sh inbox work out
```

Com a saída por projeto, arquivar um episódio publicado é mover uma pasta.

## Estrutura

```
~/video/
├── CLAUDE.md          # contexto operacional e o registro das decisões
├── README.md
├── requirements.txt
├── docs/              # o porquê de cada medição; índice em docs/README.md
├── marca/tokens.toml  # a fonte da verdade do visual, lida pelos scripts
├── scripts/           # ver o catálogo em docs/README.md
├── importado/         # código de terceiros EM VALIDAÇÃO, fora do fluxo
├── inbox/             # (ignorado) o vídeo do celular chega aqui
├── work/              # (ignorado) intermediários, descartável
├── out/<ep>/          # (ignorado) uma pasta por episódio
│   └── testes/<rodada>/   #          variante em julgamento
├── models/            # (ignorado) modelos Whisper
├── .secrets/          # (ignorado) OAuth do YouTube, modo 700
└── .venv/             # (ignorado)
```

## Onde está o porquê

O `CLAUDE.md` é o contexto operacional: o que está decidido, o que foi medido e
o que não se reabre sem motivo novo. Os documentos de `docs/` guardam as
medições inteiras, e o índice deles está em `docs/README.md`.

Quatro decisões que economizam tempo de quem chegar agora:

- **auto-editor removido.** Corte por energia não distingue pausa de fala
  (lixo) de pausa musical (conteúdo), e erra com mais confiança justamente onde
  o silêncio é mais limpo. Medido: 2% de redução, nos lugares errados. Os quatro
  gaps de silêncio do ep00 estão todos musicalmente ocupados — 100% de falso
  positivo.
- **Normalizar antes de cortar.** Decodificar 4K60 HEVC em software leva dezenas
  de minutos; depois do downscale, ~2 min.
- **Resolve MCP descartado** — exige a licença Studio.
- **Reconhecimento automático de acordes descartado** — ver "Episódio
  instrumental".

## Licença

Scripts próprios. As ferramentas usadas mantêm suas licenças (ffmpeg,
faster-whisper, librosa, Syncthing). O material em `importado/` é MIT, com a
cópia da licença original ao lado.
