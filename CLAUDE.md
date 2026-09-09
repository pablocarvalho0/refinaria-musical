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
├── out/
│   ├── <projeto>/   # UMA PASTA POR EPISÓDIO. Tudo que sai dele mora aqui:
│   │   │        #   _norm.mp4 (trabalho: video pronto, audio cru),
│   │   │        #   _audio.mp4 e _final.mp4 (entregaveis),
│   │   │        #   .txt, .segmentos.txt, .srt, .ass
│   │   └── testes/<rodada>/   # VARIANTE EM JULGAMENTO, nunca solta acima.
│   │            #   Uma pasta por rodada de comparação. Descartável.
│   │            #   Ver "Rodada de teste".
│   └── marca/       # artes do marca.py. Não é episódio — é a exceção.
├── marca/      # tokens da identidade visual. Versionado.
├── scripts/    # versionado
├── docs/       # registro das decisões de arquitetura. Versionado.
├── importado/  # codigo de terceiros EM VALIDACAO. Fora do fluxo oficial.
├── models/     # modelos Whisper baixados. Descartável (redownload).
├── .secrets/   # credencial OAuth e token do YouTube. 700, arquivos 600.
└── .venv/      # ignorado pelo git
```

`inbox`, `work`, `out`, `models`, `.secrets` e `.venv` estão no `.gitignore`.
**Nunca versionar mídia nem pesos de modelo.**

Os textos derivados da transcrição (`.txt`, `.segments.tsv`, `.segmentos.txt`,
`.srt`, `.ass`) ficam em `out/`, não em `work/`: são a fonte da verdade do
episódio, custam alguns KB, e `work/` existe para ser apagado sem pensar.

**A saída é por projeto: `out/<projeto>/`.** Os scripts criam e resolvem a
pasta sozinhos — ninguém digita o caminho. Ver "Pasta de saída por projeto".
O `work/` continua raso de propósito: é lixo por design, e organizar lixo é
trabalho que não paga.

## Fluxo

**Cada script tem uma responsabilidade só.** O `processa.sh` cuida do vídeo,
o `audio.sh` cuida do áudio, e eles não se sobrepõem. O `_norm.mp4` é arquivo
de trabalho — vídeo pronto, áudio ainda cru. O entregável é o `_audio.mp4`.

Abaixo, `<ep>` é o nome do episódio, e é ele que dá nome à pasta de saída.
Nenhum comando precisa dizer onde escrever: os scripts resolvem `out/<ep>/`
sozinhos a partir do caminho que recebem.

```bash
cd ~/video && source .venv/bin/activate

# 0. Confere a orientação do que chegou (vertical e horizontal convivem)
./scripts/sonda.sh

# 1. Vídeo: 4K HEVC -> 1080p60 H.264 (ou 1080x1920, se o master for
#    vertical). O áudio é copiado, não tratado.
#    Também extrai o .wav de 16 kHz para a transcrição.
#    Cria out/<ep>/ e imprime o projeto que resolveu.
./scripts/processa.sh ~/video/inbox/<ep>.mp4

# 2. Transcreve (GPU). SEMPRE do .wav do _norm, nunca do áudio tratado.
#    --word-timestamps grava o sidecar .words.tsv, insumo da legenda.
./scripts/transcreve.sh ~/video/work/<ep>.wav --model large-v3 --word-timestamps

# 3. Classifica fala/música e mede a zona cinzenta
python scripts/segmenta.py ~/video/work/<ep>.wav   # -> out/<ep>/<ep>.segmentos.txt

# 4. Áudio. Se a zona cinzenta passar de 10%, use --uniforme.
#    Acha o segmentos.txt do episódio sozinho e confere que é dele.
./scripts/audio.sh ~/video/out/<ep>/<ep>_norm.mp4              # por classe
./scripts/audio.sh ~/video/out/<ep>/<ep>_norm.mp4 --uniforme   # classe única

# 5. Legenda: reagrupa as palavras em cues e aplica o glossário.
#    O .srt é único e sobe separado no YouTube. O .ass carrega a aparência,
#    então sai um por formato, com o estilo vindo de marca/tokens.toml.
python scripts/legenda.py ~/video/work/<ep>.words.tsv \
    --segmentos ~/video/out/<ep>/<ep>.segmentos.txt              # -> .16x9.ass
python scripts/legenda.py ~/video/work/<ep>.words.tsv \
    --segmentos ~/video/out/<ep>/<ep>.segmentos.txt --formato 9x16   # -> .9x16.ass

# 5b. Confere que a legenda é legível sobre o vídeo real, não sobre um cinza
python scripts/valida-legenda.py ~/video/out/<ep>/<ep>_audio.mp4 \
    ~/video/out/<ep>/<ep>.16x9.ass

# 6. Humano cola a transcrição no chat -> recebe cortes.txt e as
#    correções de texto novas (que viram linhas do glossario.tsv)

# 7. Aplica os cortes ao entregável
./scripts/corta.sh ~/video/out/<ep>/<ep>_audio.mp4 ~/video/work/cortes.txt

# Queimar a legenda (só no vertical; no YouTube o .srt sobe separado):
ffmpeg -i <entrada>.mp4 -vf "ass=out/<ep>/<ep>.9x16.ass" \
    -c:v libx264 -crf 20 -preset fast -pix_fmt yuv420p -r 60 \
    -c:a copy -metadata:s:a:0 language=por <saida>.mp4

# Medir loudness de qualquer arquivo, separando fala de música:
./scripts/mede-audio.sh <arquivo> ~/video/out/<ep>/<ep>.segmentos.txt
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

## Pasta de saída por projeto — 05/09/2026

**Cada episódio tem uma pasta em `out/`, e tudo que ele gera mora lá.**

O `out/` raso não escalou. Em 05/09 ele tinha 41 arquivos de 4 masters, e o
`improviso_4` sozinho respondia por 9 deles — `_v`, `_vg`, `.v1`, `.v2`,
`.v3`, mais os `_norm`, `_audio` e `_final` de cada. O mesmo vídeo gera
cortes diferentes e testes de dinâmica distintos, e o **nome do arquivo era
a única coisa separando um do outro**. O modo de falha é o mesmo já
registrado para os dois entregáveis da v2 do `processa.sh`: publicar o
errado é silencioso, só se percebe assistindo.

Depois: 5 pastas, entre 1 e 11 arquivos cada.

### Um nível, não dois

A tentação era `out/<ep>/<entrega>/`. Não cabe: a transcrição, o `.srt` e o
`segmentos.txt` são do **episódio inteiro**, não de uma entrega, e num
segundo nível não teriam onde morar. Os sufixos que já existem (`_v`,
`_cover`, `.v1`) distinguem a entrega dentro da pasta, de graça.

### Quem resolve a pasta é o script, não quem digita

`projeto_de`, no `lib.sh`, com espelho em `scripts/projeto.py`. Quatro
degraus, do mais explícito ao mais adivinhado:

1. `$PROJETO`, se setado — o escape hatch, como `ORIENTACAO`;
2. o caminho já está sob `out/<X>/` → `X`. Cobre todo o meio do fluxo:
   `audio.sh`, `corta.sh` e `legenda.py` recebem o que o passo anterior
   já pôs na pasta certa;
3. a maior pasta de `out/` que prefixa o basename. É o que faz
   `work/improviso_4_v.wav` voltar para `out/improviso_4/` — e é por isso
   que **o `work/` não precisou mudar de forma**;
4. o basename sem extensão e sem sufixo de etapa. Só sobra para a primeira
   execução, com o master vindo do `inbox`, onde o nome está limpo.

Nenhum deles é silencioso: todo script imprime `==> Projeto: <nome> (por
<degrau>)` antes de escrever. Escrever na pasta errada é exatamente o tipo
de erro que só aparece três passos depois.

**O degrau 4 precisou aprender os sufixos com ponto.** Sem eles,
`ep00.16x9.ass` abria uma pasta `out/ep00.16x9/` — apareceu no plano de
migração, antes de qualquer arquivo se mover. Hoje o degrau tira `_norm`,
`_audio`, `_final`, `_legendado`, `_work48`, `.16x9`, `.9x16`, `.words`,
`.segments`, `.segmentos` e `.v<N>`, em laço até estabilizar.

**A regra está escrita duas vezes** porque metade do pipeline é shell e
obrigar o `processa.sh` a subir um interpretador só para saber onde
escrever seria pior. O que sustenta o espelho não é disciplina:
`./scripts/testa-projeto.sh` roda os dois lados sobre 16 casos e falha se
discordarem em um só.

### O `work/segmentos.txt` era um nome global, e isso mordia

O `segmenta.py` escrevia sempre em `work/segmentos.txt` — sem o nome do
episódio. Processar dois masters em sequência fazia o segundo sobrescrever
o primeiro **em silêncio**, e o `audio.sh` do primeiro passava a mascarar
com as regiões do segundo: fala tratada como música e vice-versa, arquivo
íntegro, nenhum erro. Agora sai em `out/<ep>/<ep>.segmentos.txt`.

O nome antigo continua sendo aceito como queda, para os episódios que já o
têm — mas o `audio.sh` ganhou uma guarda: **compara a duração declarada no
cabeçalho do `segmentos.txt` com a do vídeo** e recusa acima de 1s de
diferença. Não custa medição nova, o número já está no arquivo. Medido:

| episódio | segmentos | vídeo | delta |
|---|---|---|---|
| ep00 | 189,616s | 189,617s | **0,001s** |
| improviso_2 | 289,355s | 289,367s | **0,012s** |
| improviso_3 | 101,696s | 101,700s | **0,004s** |

12 ms no pior caso contra 1s de tolerância — a margem é de duas ordens de
grandeza, então a guarda não vai dar falso positivo. E ela pegou o caso
real: um vídeo de teste de 3s casou com o `work/segmentos.txt` de 101,696s
do `improviso_3` sem uma palavra de aviso, antes da guarda existir.

### Regressão: zero

O `ep00` regerado pelo `legenda.py` novo sai **byte a byte igual** ao da
versão do `HEAD` rodada sobre o mesmo `words.tsv`, em `.srt` e em `.ass`.
(Ele difere do arquivo que estava em `out/` desde 30/08, mas essa diferença
é do commit `23514b6` — a correção do gap que saía da palavra —, que nunca
tinha sido reaplicada ao episódio. A regeneração aplicou.)

Migrados 41 arquivos, 1.627.661.014 bytes antes e depois.

### O que ficou de fora

- **`work/` continua raso**, de propósito. É descartável por definição, e o
  degrau 3 faz o nome dele voltar para a pasta certa sem que ele mude.
- **`out/marca/`** não é episódio: são as artes do `marca.py`. É a única
  pasta de `out/` que não segue a regra, e fica registrado aqui para
  ninguém tentar "consertar".

## Rodada de teste — 05/09/2026

**Arquivo que existe para ser julgado mora em `out/<ep>/testes/<rodada>/`,
nunca solto na pasta do episódio.**

A pasta por projeto resolveu o `out/` raso e não resolveu o que acontece
dentro dela quando se compara variantes. Medido no mesmo dia: uma única
rodada de quatro opções do `improviso_4` pôs **dez arquivos** em
`out/improviso_4/` — seis intermediários (`_a_`, `_b_`, `_c_`, em `_norm` e
`_audio`) e quatro montagens —, ao lado do corte aprovado. É a falha dos 41
arquivos outra vez, um nível abaixo: **o nome do arquivo voltou a ser a
única coisa separando o que se publica do que ainda se está julgando**, e
publicar o errado continua sendo silencioso.

Depois: `out/improviso_4/` com 2 arquivos — o corte aprovado e o `.txt` do
episódio — e duas rodadas, de 6 e 10.

### Isto NÃO reabre o "um nível, não dois"

Lá o que se recusou foi uma pasta por **entrega**, e o argumento era que a
transcrição, o `.srt` e o `segmentos.txt` são do episódio inteiro e num
segundo nível não teriam onde morar. Esse argumento continua de pé e é
justamente ele que desenha a regra aqui: a pasta é por **rodada de teste**,
e o que vai nela é exatamente o material que **não** é do episódio inteiro
— render descartável, que existe para ser comparado e depois apagado.

### `RODADA=<slug>`, como `PROJETO=` e `ORIENTACAO=`

Quem resolve a pasta continua sendo o script, não quem digita — uma
convenção que exigisse digitar caminho seria violada na segunda semana.

```bash
RODADA=2026-09-05-dinamismo ./scripts/vertical.sh inbox/improviso_4.mp4 ...
```

Todo script imprime, antes de escrever, `Rodada de teste: <slug> — NÃO é
entregável`, pelo mesmo motivo que já imprime o degrau do projeto.

**São duas variáveis, e confundi-las é o modo de falha:**

| | é |
|---|---|
| `PROJETO_RAIZ` | `out/<ep>/`. Quem **procura** insumo procura aqui, com ou sem rodada. |
| `PROJETO_DIR` | onde **esta execução** escreve: a raiz, ou a pasta da rodada. |

O `audio.sh` procura o `segmentos.txt` na rodada, depois na raiz do
episódio, depois no `work/`. Sem o segundo degrau, **todo `audio.sh` sob
rodada não acharia o arquivo e mandaria usar `--uniforme`** — a cadeia
errada, sem erro nenhum, que é o modo de falha que a guarda de duração já
existe para pegar. Testado no `ep00`: sob rodada ele achou
`out/ep00/ep00.segmentos.txt` e escreveu em
`out/ep00/testes/<rodada>/ep00_audio.mp4`, sem tocar no entregável.

**Texto do episódio ignora a rodada.** `transcreve.py`, `segmenta.py` e
`legenda.py` chamam `pasta_episodio`, não `pasta_projeto`: a transcrição, o
`.segmentos.txt`, o `.srt` e o `.ass` são iguais para todas as variantes que
se compara, e se seguissem a rodada cada rodada teria a sua cópia e a
seguinte não acharia a anterior. Eles anunciam isso — `Rodada X não vale
aqui: texto é do episódio` —, porque **rodada que não vale em algum lugar
tem de dizer que não vale**.

O slug aceita só `[A-Za-z0-9._-]`; barra e `..` são recusados nos dois
espelhos, senão um `RODADA=../fuga` escreveria fora da pasta do episódio.
A convenção é `AAAA-MM-DD-assunto`, que ordena sozinho.

### Promover é mover, e apagar é apagar uma pasta

Variante aprovada sobe para `out/<ep>/` com nome de entregável, e a rodada
inteira pode ir embora. É a mesma economia da saída por projeto: arquivar e
limpar são um `mv` e um `rm -r`, não uma triagem por nome de arquivo.

### O teste cresceu junto

A regra continua escrita duas vezes (`lib.sh` e `scripts/projeto.py`), e
agora ela decide **duas** coisas — o nome do projeto e a pasta de escrita —,
ou seja, há duas maneiras de os espelhos divergirem. O
`./scripts/testa-projeto.sh` passou a conferir 18 casos de nome mais quatro
de pasta: com rodada, sem rodada, a raiz do episódio que não se move, e os
slugs recusados.

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
- `docs/03-sincronismo-multipista.md` — como sincronizar gravações separadas
  da mesma música, medido em 30/08/2026 nos dois projetos de `~/Music/
  Projetos`. **Ler antes de tentar casar duas tomadas por correlação** — a
  correlação global falha em música repetitiva e falha mentindo.

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

### O denoise raspa sinal, e agora tem número — 05/09/2026

Medido no cover instrumental do `improviso_3` (violão solo, 60,7s), ao montar a
cadeia do `violao.sh`. **Neste material não existe piso de ruído**: acima de
120 Hz as janelas quietas ficam 37 a 58 dB abaixo do espectro médio. Não há o
que o `afftdn` remova — então o que ele remove é sinal:

| ajuste | Δ agudo nos ataques | Δ profundidade |
|---|---|---|
| **`afftdn=nr=10:nf=-30` (o do `audio.sh`)** | **−2,60 ± 0,29 dB** | +0,63 |
| `nr=6:nf=-40` | −0,68 ± 0,13 | +0,36 |
| `nr=3:nf=-50` | −0,07 ± 0,05 | +0,08 |
| `anlmdn` | +0,71 | (atrasa 7,91 ms) |

2,60 dB acima de 4 kHz nos ataques, que num dedilhado é a unha. É a mesma coisa
que a seção acima já tinha visto pelo outro lado, sem número: as consoantes
degradadas de `microfonezinhos, olha`. **Confirma a suspeita, não fecha a
pendência** — a medição é em violão solo, e a cadeia de FALA do `audio.sh` roda
sobre fala. Trocar `afftdn` por high-pass é o candidato claro, e precisa ser
medido num episódio com fala antes de entrar.

**Compressor achata o dedilhado; ganho lento entrega o mesmo nivelamento sem
cobrar nada.** As duas colunas da direita são o preço:

| | Δ espalhamento ST | Δ profundidade | Δ ataque |
|---|---|---|---|
| rider ±3 dB | −1,76 LU | **+0,20 dB** | 0,00 ms |
| `acompressor −18 dB 3:1` (o do `audio.sh`) | −1,63 LU | **−7,66 dB** | −4,96 ms |

Mesmo efeito útil, 7,66 dB de profundidade a menos. Vale a ressalva simétrica à
do denoise: é violão solo.

**E o rider não é grátis fora do material em que foi calibrado.** O `--rider 3`
padrão do `violao_dsp.py` custou 1,76 LU de LRA no `improviso_3` — cover de
andamento firme, BPM 136,00 — e **2,92 LU no `ep00`** (7,71 sem ele, 4,79 com),
saturando o teto de −1,95 a +3,00 dB. O `ep00` é improviso livre
(autocorrelação do envelope de ataque com r = 0,174), e a dinâmica larga que ali
é *música* o rider lê como erro de volume — contra o critério de "LRA: preservar"
da classe MÚSICA. Em improviso, medir a grade antes de aceitar o padrão
(0 → 7,71; 1 → 6,19; 1,5 → 5,76; 2 → 5,37; 3 → 4,79) e levar as variantes ao
ouvido, não ao número. O reverb não é o culpado: ele *alarga* o LRA em +0,31 a
+0,41 LU.

**Medir transiente é pareado, nota a nota.** A primeira comparação de reverb
acusou a convolução atrasando o ataque em +2,83 ms — com erro-padrão de 1,94 ms
naquela mediana. Refeito pareado, as nove configurações ficaram entre +0,00 e
+0,04 ms: a diferença não existia. É a mesma lição da métrica que mentiu na
identidade visual, num sinal em vez de numa cor.

Detalhes e o resto do trabalho em `docs/05-cover-hard-days-night.md`.

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

## Ritmo da legenda por formato — medido em 05/09/2026

O `improviso_3` (vertical, Reel) mostrou que a legenda do longo e a do corte
vertical não querem o mesmo ritmo. O horizontal segue a norma de leitura; o
vertical passou a ter o seu, declarado em `marca/tokens.toml`:

```toml
[formato.9x16]
chars_por_cue = 40
dur_minima = 0.70
```

O `16x9` não declara nenhum dos dois e fica com a norma do topo do
`legenda.py` (84 caracteres, 1,20s). **O `ep00` em 16x9 sai byte a byte igual
ao de 30/08** — a mudança inteira é inerte onde não há defeito.

**char/s NÃO é o critério no vertical, e a medição diz por quê.** Encurtar o
cue *piora* a métrica, porque a duração encolhe junto com o texto:

| teto | cues | duração média | char/s máx |
|---|---|---|---|
| 84 (norma) | 5 | 3,74s | 24,5 |
| 28 | 12 | 1,55s | 32,9 |
| 20 | 14 | 1,28s | 33,3 |

Os 17 char/s da norma pressupõem duas linhas lidas em sacadas; num cue de três
palavras o olho pega tudo num golpe. O critério que vale ali é o piso de
duração — que o cue não pisque —, e quem o guarda é `dur_minima`. O relatório
do `legenda.py` troca de número sozinho conforme o ritmo, para o alerta não
virar ruído: com ritmo próprio ele imprime `piso:` e aponta quem pisca; na
norma segue apontando `rápido demais`.

### O gap entre cues estava saindo da palavra

`ajusta_tempos` calculava o fim assim:

```python
limite = próximo_início - GAP_MINIMO
fim = min(fim_da_última_palavra + FOLGA_FIM, limite)
```

Com as palavras coladas, esse `min()` puxava o fim para **antes** da última
palavra terminar: ela sumia da tela enquanto ainda estava sendo dita. O
respiro de 0,08s entre cues estava sendo cobrado da fala.

Agora o gap sai só do espaço que sobra; sem espaço, ele cede e a palavra fica
inteira. Medido no `improviso_3` com cue de 28 caracteres: **7 dos 12 cues
perdiam 80 ms** — o valor exato do `GAP_MINIMO`. Depois: 0 de 12.

Com cue longo o defeito quase não aparecia (1 de 5 no `ep00`), e é por isso
que sobreviveu até aqui: **o número de fronteiras é que expõe o erro, não o
tamanho do arquivo.** Quem viu primeiro foi o autor, na tela, antes de haver
número — a medição veio confirmar, não descobrir.

### Cue não termina em palavra funcional

Encurtar o cue trouxe outro defeito, e este também apareceu na tela primeiro:
a frase não se completava numa visada. O script fechava o cue onde os
caracteres acabavam, sem noção de sintagma, e **aumentar o teto só mudava o
lugar da emenda ruim**:

```
28:  "vou fazer uma inveja para" / "vocês..."
34:  "vou fazer uma"             / "inveja para vocês..."
40:  "vou fazer uma inveja"      / "para vocês..."
```

`ajusta_fronteiras` empurra para o cue seguinte a preposição, artigo ou
conjunção que ficou no fim. Só age onde o cue fechou por falta de espaço:
fecho por pontuação ou por pausa já cai em fronteira boa, e mexer ali seria
desfazer o que o texto mandou.

**Verbo ficou de fora de propósito.** "vou", "quero", "fazer" também pedem
complemento, mas adivinhar quando recuaria o cue até esvaziá-lo. O custo é
visível e aceito: no `improviso_3` sobrou um corte em `"não quero fazer" /
"corte não"`. Lista fechada de classe gramatical é regra; lista de verbos
seria palpite.

Com teto 40 e a regra, o episódio fecha em 8 cues de 2,33s, sete deles em
sentido completo. Acima disso o ganho some: 46 volta a cortar no meio
("tomara que dê / certo") e o cue começa a estacionar de novo.

### O `.srt` não segue o formato

`.srt` e `.ass` saíam dos mesmos cues, e o `.srt` não tem formato. Com ritmo
por formato, rodar o vertical **reescreveria em silêncio** a legenda do longo
com cues de três palavras.

O `.srt` passa a sair sempre da norma de leitura; só o `.ass` pega o ritmo do
formato. É o que preserva o que a decisão de 30/08 protegia — o corte vertical
tirado do longo continua barato, porque o texto e os tempos que o YouTube
recebe não dependem de qual formato foi gerado por último.

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

## Identidade visual — medida em 30/08/2026

**`marca/tokens.toml` é a fonte da verdade do visual, e `scripts/marca.py` é
quem desenha.** Episódio novo sai por ali. (O `capa_arte.py` foi solução pontual
das primeiras publicações e migra para os tokens quando for reusado.)

**A paleta é terracota/salmão, extraída do material escrito do autor**
(`~/Documents/proj-harmonia`), e a tipografia da marca é Bitstream Charter.
Uma primeira proposta em turquesa foi descartada: o argumento que a sustentava
— "o acento precisa contrastar com o material, que é 96% quente" — não
sobreviveu à medição seguinte, que estabeleceu que **o acento nunca vai sobre a
foto**. Detalhes e a lição sobre métrica que mente em `docs/04-identidade.md`.

A aparência do canal vive em `marca/tokens.toml` e é **lida pelos scripts**,
não consultada por uma pessoa. Um manual de marca é lido duas vezes e
esquecido; o que sobrevive a 47 episódios é o valor que o script aplica
sozinho. O porquê de cada número está em `docs/04-identidade.md`.

O `legenda.py` ganhou `--formato`, e há dois: `16x9` (YouTube longo) e `9x16`
(Shorts e Reels). O `.srt` continua único — é texto e tempo, sobe separado. O
`.ass` carrega a apresentação, então sai um por formato: `<base>.16x9.ass` e
`<base>.9x16.ass`. Sem o sufixo, gerar o vertical apagava o horizontal em
silêncio.

**A métrica da fonte foi medida, não estimada.** Renderizando com o próprio
libass em seis tamanhos, a largura de uma linha em Inter Bold é exatamente
linear: `n_caracteres × 0,4119 × tamanho`, com a caixa a `0,8148 × tamanho`.
É isso que permite dimensionar um formato novo por cálculo. Se a fonte mudar,
remedir.

**O vertical não é o horizontal reescalado.** O critério é caracteres por
linha — 29 contra 42 —, porque linha curta lê melhor em tela pequena e em
movimento. Daí fonte 78, margem lateral 60 e até 3 linhas.

### O que só apareceu medindo: metade das linhas saía da tela

O `.ass` usa `WrapStyle: 2`, que desliga a quebra automática do libass: a linha
que sai do Python é a que vai para a tela, inteira. E o `quebra_linhas` tratava
os 42 caracteres do 16:9 como se fossem universais. No vertical, com fonte 78,
**10 das 16 linhas do `ep00` e 17 das 32 do `improviso_2` saíam da tela** — a
pior com 646 px para fora, texto que não existia para quem assistisse, sem uma
única mensagem de erro.

A correção separou dois números que estavam confundidos num só:

- **o teto de 84 caracteres por cue é norma de leitura** e define os tempos.
  Continua no `legenda.py`, igual nos dois formatos, porque texto e tempo não
  podem divergir entre o longo e o corte vertical tirado dele — é isso que
  torna o corte barato;
- **onde a linha quebra é apresentação** e foi para os tokens.

  > **Revisto em 05/09/2026, e a separação sobreviveu — mudou onde ela passa.**
  > O ritmo do cue virou token de formato (`chars_por_cue`, `dur_minima`): o
  > vertical fecha em 40 caracteres, o horizontal segue nos 84. O que protegia
  > o corte barato não era os dois formatos terem os mesmos cues — era o
  > **`.srt`** não depender de formato nenhum, e ele agora sai sempre da norma.
  > Ver "Ritmo da legenda por formato".

Verificado depois: o `.ass` de 16:9 saiu byte a byte igual ao de antes da
mudança, e os cues dos dois formatos são idênticos por diff.

### O contorno é o que sustenta a legenda, e agora tem número

`scripts/valida-legenda.py` renderiza cada cue com e sem a legenda, usa os
pixels que mudaram como máscara e mede contraste WCAG contra o que havia por
baixo. No `ep00`:

| | pior contraste sem contorno | pixels abaixo de 4,5:1 | com contorno |
|---|---|---|---|
| 16:9 | 1,2:1 | 7,6% | 11,5:1 |
| 9:16 | 1,6:1 | 12,0% | 11,5:1 |

Sem o contorno, 7,6% do texto no horizontal e 12,0% no vertical ficariam
ilegíveis, e o pior caso é branco sobre parede branca estourada. Com ele, o
texto passa a ser julgado contra o próprio contorno e o fundo deixa de
importar. Quem quiser afinar o contorno por estética tem aqui o número a
vigiar.

### Cartela sobre imagem precisa de scrim, e isso é medição — 05/09/2026

O que vale para a legenda vale mais ainda para a cartela, que é texto parado
sobre um frame inteiro. Medido nas cartelas do cover do `improviso_3`, banda
por banda: **não existe faixa horizontal onde branco puro alcance 4,5:1** — o
p95 de luminância vai de 0,33 a 0,84 nas doze bandas, ou seja 1,2:1 a 2,7:1 em
qualquer lugar do quadro. Sem scrim, o texto dos créditos mede **1,0:1**:
branco sobre branco, invisível, sem um único aviso.

Com `scrim_forca = 0,72`: abertura 9,3–10,6:1, créditos 6,5:1, **0,0% de pixel
abaixo do limiar**, medido no arquivo já encodado. **Procurar a faixa boa do
frame não é alternativa** — aqui não há faixa boa, e é isso que torna o scrim
regra e não gosto. É a mesma conclusão que a capa já tinha registrado: o que
falta é escurecer o fundo, não clarear a letra.

**Ancorar pela caixa de tinta, não pela soma das alturas de linha.** A primeira
versão da cartela terminava 4 px dentro da safe area — o descendente do `y` mais
o contorno, que altura de linha nenhuma prevê. Quatro pixels somem atrás dos
botões do Reels sem nada acusar. Desenhar, medir com `getbbox` e só então
posicionar.

### Duas armadilhas silenciosas de ffmpeg

**`-ss` antes de `-i` rebaseia os timestamps para zero**, e o filtro `ass`
passa a procurar a legenda na hora errada — o frame sai limpo e a medição
inteira vira fundo contra fundo, sem acusar nada. Use `-copyts`.

**`%` solto no `drawtext` descarta o rótulo inteiro** com um warning `Stray %`.
O texto precisa chegar ao filtro como `\%`, depois de o bash e o parser do
filtergraph comerem uma barra cada um.

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

## Sincronismo de múltiplas tomadas — 30/08/2026

Dois projetos fora deste repositório reusam estes scripts e o `lib.sh`:
`~/Music/Projetos/like-a-stone` (três overdubs de violão, mix no Audacity) e
`~/Music/Projetos/oficina-g3` (violão + bateria). Cada um tem `CLAUDE.md`
próprio com as medições; o que generaliza está em
`docs/03-sincronismo-multipista.md`.

`~/Music/Projetos/CLAUDE.md` reúne o que vale para todos eles — e é o arquivo
que carrega sozinho quando a sessão é aberta lá dentro, situação em que **este
arquivo aqui não carrega**, porque `~/video` não é pai de `~/Music`. Há outros
seis projetos naquela pasta ainda não processados, cinco deles com a mesma
forma do `like-a-stone` (`.aup3` + `.mp4`), ou seja, com o sincronismo já
gravado esperando ser lido.

Duas ferramentas novas em `scripts/`, úteis para qualquer par de gravações:

```bash
python scripts/alinha-faixas.py REFERENCIA.wav OUTRA.wav   # WAV mono 48 kHz
./scripts/mixa-alinhado.sh REFERENCIA OUTRA OFFSET_MS [PREFIXO]
```

Três coisas que valem para além delas:

**Procure a medida antes de estimar o sinal.** No `like-a-stone` o sincronismo
já estava gravado no `.aup3` do Audacity — a tabela `project` guarda a timeline
em XML binário, e o `offset` de cada `<waveclip>` é exato. A correlação entrou
como segunda opinião e bateu dentro de 1 amostra. É o mesmo princípio dos gaps
de silêncio do `ep00`: preferir o dado que existe à heurística sobre o sinal.

**Correlação global mente em música repetitiva.** Medido no `oficina-g3`: o lag
saltava entre −6,4 s e −17,9 s com razão pico/ruído acima de 8 em *todas* as 23
janelas. Música casa consigo mesma a cada compasso, então a correlação sempre
acha um pico convincente, em qualquer lugar — e a confiança do pico não detecta
o erro. O que funciona é ancorar numa passagem curta que o autor aponte,
correlacionar **envelope de ataque** (timbre separa os instrumentos, ataque é o
que compartilham), e olhar a separação do segundo candidato: 64% do melhor era
confiável, os empates de 93% da busca global não eram.

**Depois de achar o offset, meça a deriva.** Se a tendência for monotônica, um
offset fixo não segura a faixa. Se for flutuação sem tendência, segura. No
`oficina-g3` a tendência foi de +47 ms em 50 s — ruído — mesmo com cada faixa
flutuando ±2% de andamento por conta própria.

**A conferência é ouvir as fontes separadas**, uma em cada canal. A soma
esconde erro de sincronismo: dois ataques a 80 ms viram um ataque gordo.

### Armadilhas de ffmpeg e de AAC, vistas no like-a-stone

Quatro coisas que apareceram ao montar o vídeo de lá e que mordem aqui também.

**O `scale=1920:1080` do `processa.sh` quebrava em vídeo vertical** — corrigido
em 05/09/2026, ver "Orientação do master". Dois dos três
vídeos de lá são gravados **3840x2160 com `rotation=-90`** nos metadados: são
*exibidos* 2160x3840. O ffmpeg gira sozinho antes dos filtros (autorotate), então
o `scale` recebe o quadro já em pé. Enquanto o `scale` daqui era fixo, um vídeo
gravado com o celular em pé saía **esmagado, sem erro nenhum**. Ler `width`/`height`
não detecta: é preciso `ffprobe -show_entries stream_side_data=rotation` e trocar as
dimensões quando a rotação for ±90. Lá o sintoma foi um painel saindo 608x1080.

**O priming de 1024 amostras não é só do `audio.sh`.** Este arquivo já registrava
21,33 ms como atraso do codificador AAC, medido por correlação no `audio.sh`. Lá
o mesmo número reapareceu por outro caminho: o `.m4a` tem `elst` com
`media_time: 0`, então o priming **não é descartado na decodificação**. Antes de
comparar tempos entre um `.m4a`/`.mp4` e qualquer outra coisa, conferir o `elst`.
O sintoma é inconfundível: viés constante, idêntico para todas as fontes, valendo
exatamente 1024 amostras.

**Nitidez baixa é ausência de sinal, não erro** — e isso completa, sem contradizer,
o que a seção acima diz sobre o `oficina-g3`. Lá em cima o problema é pico alto e
*errado*, porque música repetitiva casa consigo mesma. Aqui é o oposto: uma
verificação acusou −112 ms num trecho onde a fonte medida está coberta no mix
(rms 0,0099 contra 0,0579 de outra camada) e a correlação não achava pico —
nitidez 4,2 contra 8 a 10 das medidas boas; as outras duas fontes do mesmo trecho
davam 0,00 e −0,06 ms. Juntando os dois casos: **a nitidez sozinha não confirma
nem rejeita.** Alta pode estar errada, baixa pode ser só silêncio. Ela diz onde
olhar; quem decide é medir outra fonte do mesmo trecho, ou outro trecho da mesma
fonte.

**`-t` vence `-frames:v`, e contagem de frames se fixa.** Duas armadilhas que
valem para o `corta.sh` e para qualquer concat: um `-ss` que não cai em fronteira
de frame muda a contagem de saída (a grade do filtro `fps` fecha um frame antes),
e contagem desigual quebra concat e grade mesmo quando nada está desalinhado — a
correção é `-frames:v` explícito, com os limites convertidos para **frames** antes
de virarem tempo, para os arredondamentos não se acumularem. E com `-t` e
`-frames:v` juntos o `-t` corta primeiro: o script de lá anunciava 1523 frames,
entregava 1522 e aparava 10 ms do fim do áudio.

## Publicação no YouTube — 30/08/2026

Três scripts novos, todos em `scripts/` porque servem qualquer episódio:
`youtube.py` (metadados pela Data API v3), `capa.py` (acha os frames que
merecem virar capa) e `capa_arte.py` (monta a arte da capa).

### A separação que importa: escrever metadado não é publicar

`youtube.py aplica` mexe só na parte `snippet`. Mudar visibilidade é o
subcomando `publica`, separado, e ir para `public` exige `--sim`. O motivo é
que essa é a única ação irreversível da série: vídeo que ficou público por
trinta segundos pode ter sido visto, indexado e notificado a inscritos.
`--seco` mostra tudo que seria enviado, inclusive a descrição inteira, sem
enviar nada.

### Armadilhas da Data API, todas encontradas na prática

- **`videos.update` sobrescreve a parte inteira.** Campo que não for reenviado
  dentro de `snippet` é APAGADO, não preservado. Por isso o script lê o
  snippet atual, funde e só então envia. `categoryId` é obrigatório no envio.
- **Rascunho do Studio não existe para a API.** Vídeo largado no meio do
  assistente de upload não aparece em `playlistItems`. Basta terminar o
  assistente salvando como Privado.
- **App em modo Teste mata o token a cada 7 dias.** Publicar o app tiraria
  esse limite, mas o Console exige página inicial, política de privacidade e
  termos de serviço — três URLs públicas, exigência pensada para app que
  atende estranhos. Para uso próprio não compensa: fica em Teste, com a conta
  como usuário de teste, e reautoriza quando expirar. O script avisa com
  "token inválido ou revogado" em vez de estourar erro de API.
- **"Feito para crianças" desliga os comentários, e chega ligado sem avisar.**
  O `like-a-stone` subiu com `madeForKids: True` — ninguém marcou de propósito.
  O efeito é grande e silencioso: vídeo marcado como infantil perde comentário,
  notificação para inscritos, salvar em playlist, telas finais, cards e anúncio
  personalizado. A pergunta "por que não tem comentário?" e a pergunta "marco
  como infantil?" são a **mesma pergunta**, e é fácil não perceber. Conferir
  sempre com `youtube.py lista` seguido do status, e corrigir com
  `youtube.py infantil <id> --como nao`. O campo gravável é
  `selfDeclaredMadeForKids`; `madeForKids` é derivado e leva alguns segundos
  para acompanhar — ler logo depois de escrever mostra o valor velho e parece
  que a escrita falhou.
- **Comentário não tem campo na Data API v3.** Conferido campo por campo no
  recurso `video`: não existe. Ligar, desligar ou moderar é só no Studio. O que
  a API decide é a declaração de conteúdo infantil, que por tabela desliga tudo.
- **Ao escrever `status`, mandar só os campos graváveis.** `privacyStatus`,
  `license`, `embeddable`, `publicStatsViewable` e `selfDeclaredMadeForKids`.
  Reenviar um derivado como `madeForKids` faz a chamada falhar.
- **Cota**: `lista` 1 unidade, `aplica` 50, `capa` 50, `publica` 50, contra
  10.000 por dia. Irrelevante. Só `videos.insert` pesaria (1600) — e o upload
  não está no script de propósito: subir pelo Studio dá barra de progresso e
  retomada, que a API não dá.
- Segredos em `.secrets/` (modo 700, arquivos 600, no `.gitignore`). O
  `client_secret.json` precisa ser do tipo **App para computador**; um cliente
  `web` exige URI de redirecionamento cadastrada e o fluxo local falha.

### Instagram: o que não tem script

O Reel sobe na mão. Três coisas aprendidas em 30/08/2026 que valem para os
próximos:

- **O Instagram escolhe a capa sozinho, e escolhe mal.** No `like-a-stone` ele
  pegou a cartela de créditos — fim do vídeo, escurecido, sem ninguém tocando.
  É o pior frame do arquivo. Sempre trocar: ou por um frame limpo do meio, ou
  pela vertical 1080x1920 que o `capa_arte.py` gera. No desktop nem sempre dá
  para subir imagem; no app dá.
- **"Add collaborators" é o campo que mais rende e o mais esquecido.** Marcando
  quem participou, o Reel aparece no perfil da pessoa também, com o mesmo
  contador. É o único campo do formulário que multiplica alcance de graça.
- **A legenda é arquivo, como a do YouTube.** Fica no projeto
  (`legenda-instagram.txt`), com o corte do feed em mente: o Instagram trunca
  perto de 125 caracteres, então a primeira linha tem que se sustentar sozinha.

### Escolha de capa: o que a máquina faz e o que ela não faz

`capa.py` pontua nitidez (variância do laplaciano do luma), exposição e
equilíbrio de luz, e impõe separação mínima no tempo — senão os dez melhores
são o mesmo instante dez vezes. Ele não escolhe: reduz 1523 frames a uma dúzia
de candidatos e monta a folha de contato. Expressão é julgamento humano.

**Nitidez premia textura, não composição.** Na primeira passada os doze
candidatos foram todos de trechos empilhados, porque duas pilhas de violão têm
o dobro de bordas de um plano de rosto. A correção não foi mexer na fórmula:
foi restringir a busca aos trechos de tela cheia com `--trechos`. Vale para
qualquer vídeo com layout misto.

### Duas medidas que corrigiram a arte da capa

- **Escalar primeiro, recortar depois.** Recortar 1080x1253 e escalar para
  470x720 aplica 0,435 na horizontal e 0,575 na vertical: o rosto sai
  espremido, e sem erro nenhum. Com
  `scale=...:force_original_aspect_ratio=increase` seguido de `crop` a
  proporção se mantém.
- **Contraste ruim nem sempre se conserta clareando a letra.** Na capa
  vertical o bloco cai sobre o tampo do violão e âmbar sobre âmbar some. Com o
  fundo em luma 122, **nem branco puro chega aos 4,5:1** que texto pequeno
  pede — a conta fecha em 4,34:1. O que faltava era escurecer o fundo. Com um
  scrim em rampa (`geq` sobre o alfa) o pior dos três candidatos subiu de
  3,50:1 para 4,69:1.

## Orientação do master — medido em 05/09/2026

O canal produz horizontal (YouTube longo) e vertical (Shorts e Reels), e
o `processa.sh` agora atende os dois. Quem decide é `geometria_video`, em
`scripts/lib.sh`: lê o side data `rotation`, troca as dimensões quando o
giro é ±90 e escolhe 1920x1080 ou 1080x1920. `ORIENTACAO=h|v` força, para
quando o metadado mentir.

**O modo de falha antigo era mudo.** O `scale=1920:1080` era fixo, e o
ffmpeg aplica a rotação dos metadados *antes* dos filtros (autorotate):
o `scale` recebia um quadro 2160x3840 e o espremia num 16:9. Código de
saída 0, nenhum aviso. Medido no `improviso_3`:

| | fx | fy | anisotropia |
|---|---|---|---|
| `scale=1920:1080` fixo | 0,8889 | 0,2812 | **3,16x** |
| `geometria_video` | 0,5000 | 0,5000 | **1,000** |

Conferido nos três casos que existem hoje no `inbox` — vertical 4K, 8K
horizontal e 4K horizontal: saída na dimensão certa, SAR 1:1, 60 fps CFR,
e `cropdetect` acusando área útil igual ao quadro inteiro (nenhuma barra
espúria). A prova visual é direta: no frame antigo o rosto sai achatado.

**Escalar nunca distorce, mesmo com proporção torta.** O filtro é
`scale=...:force_original_aspect_ratio=decrease:force_divisible_by=2`
seguido de `pad` e `setsar=1`. O alvo continua exato — o concat exige —
mas o que não couber vira barra preta em vez de esticão. Para uma fonte
16:9 indo a 1920x1080 é no-op, custo zero. O `setsar=1` fecha a outra
porta: SAR diferente de 1 atravessa o encode e o player estica na
exibição, mesmo sintoma por outro caminho.

`./scripts/sonda.sh` mostra a geometria do `inbox` antes de processar.
Vale rodar sempre: a orientação é invisível na listagem, e dois arquivos
que o ffprobe declara 3840x2160 podem ser um deitado e outro em pé.

### Duas armadilhas de shell, ambas descobertas testando isto

**`ffprobe -of csv=p=0` pode devolver a vírgula junto.** Num stream com
side data, `-show_entries stream=width` sai como `3840,` — o separador
de uma coluna que ficou vazia. A vírgula entra na variável e o `(( ))`
seguinte morre com `operand expected`. Usar `-of default=nw=1:nk=1`.

**`grep` sem match derruba o script inteiro sob `pipefail`.** A sonda de
rotação é um pipeline com `grep`, e material horizontal é justamente o
caso em que não há o que achar: o `grep` retorna 1, o `pipefail`
propaga, o `set -e` aborta. O sintoma foi o `processa.sh` terminando
mudo depois da linha do áudio, sem erro visível. Fechar com `|| true`.

## Vertical a partir de master horizontal — medido em 05/09/2026

O `processa.sh` resolve a orientação do master; ele não resolve o caso em que
o master é horizontal e o entregável precisa ser vertical. É o do `improviso_4`
(8K, 45,4s): plano aberto com **duas pessoas** — violão à direita, bateria à
esquerda. Um corte 9:16 guarda 31,6% da largura, e as duas ocupam a largura
inteira em todos os frames sondados.

Três enquadramentos renderizados do mesmo frame (t=40s) e olhados na tela:

| enquadramento | o que dá |
|---|---|
| corte central 9:16 | não pega ninguém: parede, um prato e um pedaço de braço |
| banda 1080x608 + fundo borrado | pega as duas, mas a imagem útil fica em 32% da altura; o resto é borrão preto em cima e laranja embaixo |
| **empilhado, 1080x960 + 1080x960** | **as duas em tamanho grande, tela cheia, sem borrão** |

`scripts/vertical.sh` faz o empilhado: dois recortes de metade da largura,
na proporção 9:8 por construção, um sobre o outro. Só é honesto porque a
fonte é 8K — cada painel vem de um recorte de 3840x3412, ou seja, ainda é
**redução**, nunca ampliação. Num master 4K o mesmo corte seria 1920x1706 →
1080x960, também redução; abaixo disso, não.

Ele segue o contrato do `processa.sh` de propósito — vídeo pronto, áudio
**copiado** e o `.wav` de 16 kHz — para que `transcreve.sh`, `segmenta.py`,
`audio.sh` e as cartelas rodem por cima sem adaptação nenhuma.

**O `split` aqui é seguro, e vale saber por quê.** É o mesmo padrão que
derrubou a IDE em 30/08, mas com um consumidor diferente: o `vstack` drena os
dois ramos em travamento, um frame de cada por vez, então nenhuma fila cresce.
O que estourava era `trim`+`concat`, em que um ramo esperava minutos pelo
outro. Medido: 1m40s de encode, sem chegar perto do teto do `ffmpeg_lim`.

`--topo-y` e `--base-y` são os dois únicos números que dependem da câmera —
onde a cabeça é cortada. Neste episódio, 150 no topo e 600 na base.

**A divisão precisa de um plano geral antes.** Visto na tela em 05/09/2026: o
empilhado sozinho não diz que os dois estão no mesmo cômodo — os painéis lêem
como duas gravações separadas montadas lado a lado. Com os primeiros segundos
no quadro inteiro do master, ajustado à largura e com tarja preta, a divisão
passa a ler como o que é: um take só, que abre. É o `--geral SEGUNDOS`, e a
duração do fundido é `empilhado.transicao` nos tokens.

**O fundido é overlay com alfa, não `xfade`.** O `xfade` precisa segurar um
dos lados em buffer, e aqui os dois lados saem do mesmo `split` — é a receita
exata da fila que estourou a memória em 30/08. Com `overlay` + `fade` de alfa,
o `overlay` drena os dois ramos em travamento e nada se acumula. Medido:
1m19s de encode com três ramos de 8K, sem chegar perto do teto do `ffmpeg_lim`.

**Quem vai em cima é decisão de conteúdo.** No `improviso_4` é o violão, com
`--troca`: é o instrumento que o canal é sobre, e é o que a piada da abertura
promete. Trocar de painel troca também os deslocamentos — eles são do
recorte, não da pessoa.

### O zoom-out do plano fechado — 05/09/2026

`--fechado SEGUNDOS --fechado-x PX` põe um terceiro ato na frente: o 9:16
mais apertado que o master permite, tela cheia, que depois **afasta** até o
plano geral. A ordem final é fechado → geral → empilhado, e cada transição
diz uma coisa: o afastamento apresenta a sala, a divisão apresenta os dois.

**Nenhum filtro de zoom deste ffmpeg serve, e vale saber por quê antes de
tentar de novo:**

| | por que não |
|---|---|
| `crop` | reavalia só `x` e `y` por frame; `w`/`h` são resolvidos uma vez, na configuração. Desloca a janela, não a abre. (`eval` nem existe como opção aqui — 6.1.1 devolve `Option not found`.) |
| `zoompan` | só sabe **aproximar**: `z` tem piso em 1. Para afastar seria preciso alimentá-lo com a tela larga já pronta, e aí o plano fechado sairia de uma ampliação de 3,2x de um quadro de 1080 px |

O que funciona é `scale`, cujos `w`/`h` são ajustáveis em runtime (o flag `T`
em `ffmpeg -h filter=scale`). `scripts/zoom-cmds.py` gera um comando por
frame do master e o `sendcmd` os aplica. **Cada frame continua sendo uma
redução direta do 8K** — em nenhum instante se amplia algo já reduzido.

**O recentramento se prende à escala, não ao relógio.** A expressão de `x`
do `overlay` lê `overlay_w`, que é a largura que o `sendcmd` acabou de
aplicar; assim o pan e o zoom não têm como sair de fase, nem que um comando
se perca. A curva é smoothstep (3p²−2p³): zoom que começa e termina na
velocidade máxima lê como corte mal feito.

O ato fechado usa a **janela mais apertada que existe** — largura =
altura × 9/16, ou 2430 px neste master. Mais fechado que isso só ampliando.
`--fechado-x` é o centro horizontal dessa janela, em pixels do master: 5200
no `improviso_4`, que é onde o violão fica nos primeiros sete segundos.

## Resolução de entrega — 08/09/2026

**O entregável sai na maior resolução que o master sustente por REDUÇÃO.**
Não é a resolução do formato: é a que a fonte aguenta sem ampliar nada.

O `improviso_4` subiu ao YouTube em 1080x1920 vindo de um master **8K**
(7680x4320, 80,1 Mbps HEVC). O `vertical.sh` tinha `1080` e `960` escritos
em dez lugares, e nenhum deles era decisão — era o número que estava lá
quando o script nasceu. O que se jogou fora:

| | master | entregue | descartado |
|---|---|---|---|
| pixels por frame | 33,2 M | 2,07 M | **94%** |
| bitrate | 80,1 Mbps | 6,2 Mbps | — |

**O custo não é só do arquivo: é do que o YouTube devolve.** Acima de 1440p
a plataforma entrega VP9/AV1 com bitrate alto; em 1080p fica no H.264 magro.
Então subir 1080p paga duas vezes — uma na redução, outra na recodificação
que a plataforma faz por cima. Num Short de violão isso cai justamente no
detalhe de corda e no ataque da baqueta, que é o que o vídeo tem para
mostrar.

### O teste que decide a resolução é "isto ainda é redução?"

Não é "cabe no disco" nem "o formato pede tanto". Para o `improviso_4` em
2160x3840, as três cadeias fecham como redução, então 4K é honesto:

| etapa | recorte no master | saída 4K | fator |
|---|---|---|---|
| painel empilhado | 3840x3412 | 2160x1920 | 0,563 |
| plano fechado (janela 9:16 mais apertada) | 2430x4320 | 2160x3840 | 0,889 |
| plano geral | 7680 de largura | 2160 | 0,281 |

O plano fechado é o que manda: ele usa a janela mais apertada que existe
(largura = altura x 9/16), e é ali que o fator chega mais perto de 1. Num
master 4K essa mesma conta daria 1,78 — **ampliação** —, e aí o teto de
entrega cai. **A conta é por etapa, não pelo master:** basta uma etapa
ampliando para a resolução escolhida estar errada.

### Quem calcula a resolução é o script

`vertical.sh` não tem mais número de saída escrito: `RESOLUCAO=` força (como
`ORIENTACAO=` e `PROJETO=`), e sem ela o script escolhe o maior degrau de
`DEGRAUS=(1080 1440 2160 2880 4320)` que caiba sob o teto. Ele imprime qual
etapa o limitou, antes de encodar:

```
==> Saída: 2160x3840  (teto 2430 px por janela 9:16 mais apertada (plano fechado/destaque))
```

**O teto olha as etapas que a execução usa, não as que o script sabe fazer.**
Medido nos quatro casos:

| master | com `--fechado`? | teto | saída |
|---|---|---|---|
| 8K (7680x4320) | sim | 2430 (janela) | **2160x3840** |
| 8K | não | 3840 (metade) | **2880x5120** |
| 4K (3840x2160) | sim | 1215 (janela) | **1080x1920** |
| 4K | não | 1920 (metade) | **1440x2560** |

A terceira linha é a regressão que importa: onde o `1080` fixo estava certo,
a saída não mudou. E o filtro do `improviso_4` em 2160 sai **byte a byte
igual** ao que foi publicado.

`RESOLUCAO=` acima do teto não é bloqueado — só avisado, porque quem força
sabe o que quer. O aviso diz qual etapa vai ampliar.

### Cartela acompanha, e não por escala

Cartela gerada em 1080x1920 e escalada 2x para um vídeo 4K entra com texto
borrado — e aí o ganho do render some na única parte do quadro que é
tipografia pura. As cartelas se regeram em 2160x3840 **nativo**, dobrando
nos tokens só o que é medida em pixel (`largura`, `altura`, `tamanho`,
`contorno`, `sombra`, margens, `barra_largura`, `barra_gap`, `scrim_rampa`,
`scrim_folga` e os `tamanho_*` de cada cartela). Tempo, alfa e múltiplos
ficam como estão: dobrar `duracao` ou `entrelinha` mudaria a montagem, não
a resolução.

Isso virou `tokens(largura=)` no `cartelas.py` e `--largura` no
`cartelas_improviso.py`. Sem argumento, tudo se comporta como antes — o
`ep00` e as cartelas de 05/09 saem **byte a byte iguais**, e as de 2160
saem idênticas às que foram ao ar. O `--abertura-ate` também deixou de ser
número digitado à mão: é o "reveal", e quer cair num tempo forte medido
pelo `grade-musical.py --encaixa`.

### O modo de falha, outra vez, foi mudo

Ninguém viu erro nenhum. O encode saiu com código 0, o arquivo abriu, subiu
e tocou. É a mesma família do `scale=1920:1080` fixo que esmagava vertical
(ver "Orientação do master") e do `out/` raso em que o nome do arquivo era a
única coisa separando o entregável do teste: **o pipeline entrega algo
plausível e a perda só aparece assistindo.** Quem viu primeiro foi o autor,
na tela — de novo antes de haver número.


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
- [ ] **Capa vertical de Short é manual.** O `capa_arte.py` gera o 1080x1920,
      mas não achei caminho de API para o seletor de capa de Short: só o
      `thumbnails.set` 16:9, que alimenta busca e página do vídeo. A vertical
      sobe pelo Studio, na mão.
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
- [~] **Import video-use, item 4 / safe area** — resolvido por decisão, não por
      medição. O formato `9x16` põe a legenda a 25% da altura (contra 8,3% do
      horizontal), número emprestado da documentação do video-use. Decidido em
      30/08/2026 seguir assim: o padrão importado é razoável e o custo de errar
      é uma linha no `tokens.toml`. **Reabrir só se uma legenda aparecer coberta
      pela interface** — aí `./scripts/gabarito-safe-area.sh` mede em cinco
      minutos. Não é lacuna, é valor emprestado com fonte declarada.
- [x] ~~Validar o `9x16` sobre um corte vertical de verdade~~ — feito em
      05/09/2026 no `improviso_3`, gravado vertical no celular (não é crop
      do 16:9). A legenda ficou dentro do quadro e legível; o contraste sem
      contorno é **pior** que o do crop central medido antes — 32,4% dos
      pixels abaixo de 4,5:1 contra 12,0% do `ep00` —, porque a gravação é
      externa, com céu aberto e sol. Com contorno o pior caso é 11,5:1. O
      contorno é o que sustenta a legenda em locação, não a cor da letra.
- [ ] **Migrar o `capa_arte.py` para os tokens.** Ele nasceu como solução
      pontual para destravar as primeiras publicações e tem tipografia e cores
      escritas dentro do código. **O sistema canônico daqui em diante é
      `marca/tokens.toml` + `scripts/marca.py`** — episódio novo sai por ali.
      A migração é ajuste fino e não redesenho: as duas direções convergiram
      sozinhas (fundo e texto praticamente idênticos, acento a 8° de distância
      em matiz, serifa nos dois casos). Ver "Duas soluções, uma direção" em
      `docs/04-identidade.md`.

- [x] ~~`processa.sh` distorce vídeo vertical~~ — resolvido em 05/09/2026,
      no mesmo dia em que os dois primeiros verticais entraram no `inbox`
      (`improviso_3` e `20260717_113135`, ambos `rotation=-90`). Ver
      "Orientação do master", acima.
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
- No `improviso_3` (05/09/2026) três trechos precisaram do autor para serem
  resolvidos, e a probabilidade só acertou o endereço de um deles: `ideia`
  (p=0,250) e o `a` de `a gaiota` (p=0,185) estavam mesmo errados, mas
  `improvisa` fechou o episódio com p=0,447 sem que o número apontasse a
  conjugação. Quem decidiu foi ouvir. Média do episódio: 0,787 contra 0,864
  do `ep00` — gravação externa, com vento e rua, transcreve pior.

## Ao trabalhar neste projeto

- **Medir antes de otimizar.** Todas as decisões acima vieram de números, não de intuição.
  Sugestões novas devem vir com forma de medir.
- **Não sugerir subir mídia** para nenhum serviço ou para o chat.
- **Disco é o recurso apertado.** ~25 GB livres em 30/08/2026. Um episódio de 20 min em 4K60 dá ~7 GB de
  master. Limpar `work/` após aprovar, arquivar masters após publicar. Com a
  saída por projeto, arquivar é mover uma pasta — `out/<ep>/` inteira. A
  primeira coisa a apagar é `out/<ep>/testes/`: são as variantes recusadas,
  e uma rodada de quatro opções custou 376 MB.
- **Script que escreve em `out/` chama `pasta_projeto` do `lib.sh`**, nunca
  monta o caminho na mão. Em Python é `pasta_projeto` do `scripts/projeto.py`,
  e `pasta_episodio` quando o que se escreve é texto do episódio inteiro.
  Depois de mexer em qualquer um dos dois, rodar `./scripts/testa-projeto.sh`:
  a regra vive nos dois arquivos e o teste é o que impede que divirjam.
- **Comparar variantes é sempre com `RODADA=<slug>`.** Render de teste não
  encosta em `out/<ep>/` — vai para `out/<ep>/testes/<rodada>/`, e sobe para
  a raiz só quando for aprovado. Ver "Rodada de teste".
- **Fase 0 é publicar, não perfeição.** Se algo estiver bloqueando por mais de uma
  tentativa, usar o caminho lento e seguir (ex: CPU em vez de GPU).
- **Se a IDE ou o terminal fechar sozinho durante um trabalho pesado, é OOM até prova
  em contrário.** Olhar `journalctl --since today | grep -i oom` antes do log da
  aplicação. Processo pesado disparado do terminal da IDE compartilha o cgroup — e o
  destino — dela. Ver "O corte que derrubava a IDE".
- **Antes de estimar sincronismo no sinal, procure se ele já está gravado** num
  projeto de DAW. E desconfiar de correlação cruzada em material repetitivo: ela
  acha pico convincente em qualquer lugar. Ver `docs/03-sincronismo-multipista.md`.
- **A nitidez de uma correlação não confirma nem rejeita sozinha.** Pico alto
  pode ser o compasso errado (`oficina-g3`); pico baixo pode ser só a fonte
  calada naquele trecho (`like-a-stone`). Reportar sempre o valor com a nitidez,
  dizer "inconclusivo" em vez de acusar, e desempatar com outra fonte do mesmo
  trecho ou outro trecho da mesma fonte.
- **Contraste ruim quase nunca se conserta clareando a letra.** Faça a conta
  antes de mexer: com o fundo em luma 122, nem branco puro passa de 4,34:1, e o
  mínimo para texto pequeno é 4,5:1. Se a conta não fecha nem no branco, o que
  falta é escurecer o fundo — scrim, não fonte mais clara.
- **Ao recortar e escalar, escalar primeiro.** Recortar numa proporção e
  escalar para outra distorce sem erro nenhum, e rosto espremido não salta aos
  olhos numa miniatura. `scale=...:force_original_aspect_ratio=increase`
  seguido de `crop` mantém a proporção por construção.
- **A resolução de entrega se decide pela fonte, não pelo formato.** Antes de
  renderizar, faça a conta de cada etapa: se todas ainda forem redução, suba
  a resolução até onde a mais apertada permitir. Master 8K entrega 4K; master
  4K, com plano fechado, não. Cartela e legenda acompanham em pixel nativo,
  nunca escaladas. Ver "Resolução de entrega".
- **ffmpeg novo passa pelo `ffmpeg_lim` do `scripts/lib.sh`**, não pelo `ffmpeg` direto,
  sempre que processar arquivo inteiro. E desconfiar de grafo que reusa a mesma entrada
  em vários ramos: é o padrão que enfileira frames decodificados até estourar.