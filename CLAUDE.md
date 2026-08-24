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
├── out/        # entregáveis: _norm.mp4, _final.mp4, .txt
├── scripts/    # versionado
└── .venv/      # ignorado pelo git
```

`inbox`, `work`, `out` e `.venv` estão no `.gitignore`. **Nunca versionar mídia.**

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

## Pendências conhecidas

- [ ] **Áudio saindo a 96 kHz** em vez de 48 kHz. O `loudnorm` opera a 192 kHz
      internamente e vaza taxa dobrada. Corrigir com `-ar 48000` na saída de áudio,
      em `processa.sh` e `corta.sh`.
- [ ] **`corta.sh` nunca foi executado.** É a única peça da cadeia sem validação.
      Ao testar, verificar as emendas entre trechos (salto de áudio, frame preto).
- [ ] `LD_LIBRARY_PATH` ainda não está permanente — preferir um wrapper
      `transcreve.sh` a truque de `os.execv` dentro do Python.
- [ ] Marcar idioma do áudio: `-metadata:s:a:0 language=por`
      (o metadado do Samsung vem como `eng`).
- [ ] Glossário de correção de transcrição ainda não existe.

## Glossário de transcrição (em construção)

O Whisper erra vocabulário técnico. Termos a vigiar e corrigir:

- dominante secundária, empréstimo modal, tétrade, cadência de engano
- rearmonização, II-V-I, grau, campo harmônico, modo mixolídio
- Erros já observados: `Falta da YouTube` → "Fala, galera do YouTube"

## Ao trabalhar neste projeto

- **Medir antes de otimizar.** Todas as decisões acima vieram de números, não de intuição.
  Sugestões novas devem vir com forma de medir.
- **Não sugerir subir mídia** para nenhum serviço ou para o chat.
- **Disco é o recurso apertado.** ~31 GB livres. Um episódio de 20 min em 4K60 dá ~7 GB de
  master. Limpar `work/` após aprovar, arquivar masters após publicar.
- **Fase 0 é publicar, não perfeição.** Se algo estiver bloqueando por mais de uma
  tentativa, usar o caminho lento e seguir (ex: CPU em vez de GPU).