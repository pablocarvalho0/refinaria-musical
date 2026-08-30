# Pipeline de vídeo — canal de harmonia funcional

Automação de produção para vídeos de violão + fala, do celular ao YouTube.
Roda inteiramente local: nenhum arquivo de mídia sai da máquina.

## Ideia central

Vídeo é caro de processar e opaco para automatizar. Texto não é.

O pipeline converte o áudio em transcrição com timestamps logo no início, e a partir daí
tudo — corte, capítulo, legenda, descrição, escolha de trechos para Reels — vira
manipulação de texto. O vídeo só é tocado duas vezes: uma para normalizar, outra para
aplicar os cortes já decididos.

## Requisitos

- Ubuntu (testado no 24.04)
- ffmpeg
- Python 3.12

Opcionais, todos com caminho alternativo:

- GPU NVIDIA e ffmpeg com `-hwaccel cuda` — aceleram muito, mas há fallback para CPU
- Syncthing e um Android com Syncthing-Fork — só para a ingestão; ver
  [Ingestão](#ingestão--como-o-vídeo-chega-à-inbox)

## Instalação

```bash
# Sistema
sudo apt install ffmpeg mpv

# Ambiente Python
git clone <este-repo> ~/video && cd ~/video
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Estrutura de trabalho (ignorada pelo git)
mkdir -p inbox work out
```

## Ingestão — como o vídeo chega à `inbox`

O contrato do pipeline é simples: **coloque um `.mp4` em `~/video/inbox` e rode o
`processa.sh`**. Cabo USB, `adb pull`, `scp`, cartão SD — qualquer coisa serve. A pasta
é ignorada pelo git, junto com `work/`, `out/` e `models/`: o repositório versiona a
receita, não os ingredientes nem o prato.

O que descrevo abaixo é como *eu* faço, não um requisito.

### Opcional: Syncthing

Sincronização direta do celular, sem cabo e sem nuvem. No Ubuntu:

```bash
sudo apt install syncthing
systemctl --user enable --now syncthing
loginctl enable-linger $USER   # mantém rodando após logout
```

Interface em `http://127.0.0.1:8384`. Defina usuário e senha.

No celular, instale o **Syncthing-Fork** pelo F-Droid (o app oficial foi descontinuado em
dezembro de 2024). Pareie escaneando o QR de **Actions → Show ID**.

Configuração da pasta compartilhada:

| Lado | Folder Type | Motivo |
|---|---|---|
| Celular | **Send Only** | mudanças no PC não voltam para o aparelho |
| Ubuntu | **Receive Only** | o PC nunca propaga exclusões |

Destino no Ubuntu: **`~/video/inbox`, nunca `~/video`.**

> **Aponte o Syncthing só para `~/video/inbox`.** Sincronizar `~/video` inteiro colocaria
> o diretório `.git` dentro da pasta compartilhada, e com o celular em Send Only o
> Syncthing passaria a ter licença para sobrescrever e apagar objetos do repositório. Os
> masters você regrava e as transcrições você refaz; o histórico do projeto é a única
> coisa aqui que não dá para recriar.

Desative a otimização de bateria para o app e restrinja a sincronização a Wi-Fi.

## Configuração da câmera (Galaxy S23)

| Ajuste | Valor | Por quê |
|---|---|---|
| Resolução | **UHD (4K)** | o corte vertical 1080×1920 para Reels sai nativo do quadro 2160p |
| Taxa | **60 fps** | palhetada e dedilhado ficam legíveis |
| Codec | HEVC | ok — a GPU decodifica |
| HDR10+ | **desligado** | causa cor lavada após transcodificar |
| Estabilização | **desligada** | com tripé, só introduz artefato |
| Enquadramento automático | **desligado** | pode cortar o braço do violão |

Custo: ~225 MB/min. Um episódio de 20 min ocupa ~4,5 GB.

### Disciplina de gravação

O maior ganho de tempo não é software. Três hábitos convertem trabalho de edição em
metadado legível por script:

- **Falar o nome do acorde em voz alta.** A narração vira trilha de anotação: ao dizer
  "aqui entra o empréstimo modal", o transcritor carimba o timestamp.
- **Bater palma antes de refazer um take.** Pico isolado, trivial de localizar.
- **Falar antes e depois de tocar.** Delimita a região musical no texto, para o corte
  não encostar nela.

## Uso

```bash
cd ~/video && source .venv/bin/activate
```

### 1. Normalizar

```bash
./scripts/processa.sh inbox/20260824_135542.mp4
```

Converte 4K60 HEVC → 1080p60 H.264, normaliza o áudio a −14 LUFS (alvo do YouTube),
força taxa de quadros constante e extrai o `.wav` para transcrição.

Saída: `out/<nome>_norm.mp4` e `work/<nome>.wav`.

Parâmetros por variável de ambiente:

```bash
CRF=18 PRESET=slow ./scripts/processa.sh inbox/<arquivo>.mp4
```

### 2. Transcrever

```bash
./scripts/transcreve.sh work/20260824_135542.wav
./scripts/transcreve.sh work/20260824_135542.wav --model medium
```

Saída: `out/<nome>.txt` com timestamps.

Modelos: `small` (rápido), `medium` (melhor com vocabulário técnico), `large-v3`.

### 3. Decidir os cortes

Cole a transcrição no chat com o Claude e peça a lista de cortes. Ele devolve os trechos
a manter, respeitando as regiões musicais.

Formato do `work/cortes.txt`:

```
# trechos a MANTER — "início fim"
00:00:04  00:00:12
00:00:23  00:03:09
```

### 4. Aplicar

```bash
./scripts/corta.sh out/20260824_135542_norm.mp4 work/cortes.txt
```

Monta um `filter_complex` único com `trim`/`atrim` + `concat`: todos os trechos numa só
passagem do ffmpeg, sem arquivos intermediários e sem geração extra de perda.

Saída: `out/<nome>_final.mp4`.

### 5. Publicar

Upload manual no YouTube, com título, descrição e capítulos gerados a partir da
transcrição. Automação via YouTube Data API está no backlog.

Para extrair um frame para thumbnail:

```bash
ffmpeg -i out/<nome>_final.mp4 -ss 00:01:23 -vframes 1 out/frame.png
```

## Desempenho medido

Fonte: 1,4 GB, 4K60 HEVC, 3min09, no hardware descrito em `CLAUDE.md`.

| Etapa | Tempo | Saída |
|---|---|---|
| Normalização (x264 crf 23) | 2m21s | 84 MB |
| Transcrição (small, GPU) | segundos | — |

Redução de 17× no tamanho, com um único reencode.

## Manutenção

```bash
# Após aprovar um vídeo
rm work/*_cut.mp4 work/*.wav

# Espaço
df -h /home
du -sh inbox work out
```

Masters em 4K ocupam ~7 GB por 20 min. Arquive ou apague após publicar. Se você usa o
Syncthing como descrito acima, a `inbox` está em Receive Only: apagar no Ubuntu não
propaga a exclusão para o celular.

## Estrutura

```
~/video/
├── CLAUDE.md          # contexto para o Claude Code
├── README.md
├── requirements.txt
├── scripts/
│   ├── processa.sh    # normalização + extração de áudio
│   ├── transcreve.sh  # wrapper que configura LD_LIBRARY_PATH
│   ├── transcreve.py  # faster-whisper
│   └── corta.sh       # aplica cortes semânticos
├── inbox/             # (ignorado) entrada — o vídeo do celular chega aqui
├── work/              # (ignorado) intermediários
└── out/               # (ignorado) entregáveis
```

## Roadmap

**Fase 0 — publicar** (atual)
Ingestão, normalização, transcrição, corte semântico, upload manual.

**Fase 1 — qualidade**
Glossário de correção de transcrição · Demucs para separar voz e violão em stems ·
DeepFilterNet só no stem de voz · legendas `.ass` estilizadas.

**Fase 2 — escala**
WhisperX com alinhamento por palavra · export FCPXML para aplicar cortes no master 4K ·
YouTube Data API · templates de carrossel e capa · overlay de pauta e cifra via LilyPond.

## Notas de licença

Scripts próprios. Ferramentas usadas mantêm suas próprias licenças
(ffmpeg, faster-whisper, Syncthing).