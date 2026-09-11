# Índice dos documentos

O `CLAUDE.md` é o contexto operacional: o que está decidido e o que não se
reabre sem motivo novo. Aqui ficam as medições inteiras — os números, as
janelas em que foram tomados e o que cada um autoriza.

Um documento deste diretório é **registro datado**, não especificação: ele vale
para o material em que foi medido. Quando uma medição é superada, a nota fica
no topo do arquivo, e o arquivo não é apagado — saber que a direção mudou vale
mais do que a direção antiga.

| # | Documento | Do que trata | Estado |
|---|---|---|---|
| 00 | [Plano inicial](00-plano-inicial.md) | o escopo da Fase 0, escrito antes da validação prática | **superado** — descreve o auto-editor, removido. Registro histórico; não seguir |
| 01 | [Arquitetura de segmentação](01-arquitetura-segmentacao.md) | partir o episódio em FALA e MÚSICA a partir da transcrição | passos 1 e 2 medidos e em produção; 3 e 4 sem medição |
| 02 | [Import do video-use](02-import-video-use.md) | o que entrou de `browser-use/video-use` (MIT), o que foi recusado e por quê | **em validação** — nada de `importado/` é chamado por `scripts/` |
| 03 | [Sincronismo multipista](03-sincronismo-multipista.md) | casar gravações separadas da mesma música | medido; vale para `~/Music/Projetos`, fora do fluxo de episódio |
| 04 | [Identidade visual](04-identidade.md) | o porquê de cada número de `marca/tokens.toml` | vigente — é a referência de cor, tipografia e contraste |
| 05 | [Cover instrumental (improviso_3)](05-cover-hard-days-night.md) | cadeia de áudio de violão solo, reverb, cartelas e análise de seções | vigente; a medição do denoise já foi aplicada ao `audio.sh` |
| 06 | [Câmera virtual](06-camera-virtual.md) | zoom e reenquadramento animados sobre plano fixo | mecânica medida; o **ritmo** aguarda validação na tela |
| 07 | [ep00 — sonorização e edição](07-ep00-edicao.md) | o episódio de apresentação: áudio pronto, plano de imagem proposto | áudio feito; edição de imagem **não executada** |
| — | [Plano de conteúdo](fluxo-geral-teste/00-ideia-inicial.md) | análise das métricas do Instagram e a linha editorial que saiu dela | frente de conteúdo, não de pipeline |

## O que ler antes de mexer em quê

- **Filtro que muda de tamanho por frame** → [06](06-camera-virtual.md). `in_w`
  no `crop` não acompanha um `scale` com `eval=frame`, e o vídeo sai deslocado
  sem um único aviso.
- **Parâmetros das cadeias do `audio.sh`** → [05](05-cover-hard-days-night.md).
  É onde estão os números que tiraram o denoise da cadeia e que dizem o preço do
  compressor.
- **Cor, fonte, contorno, scrim ou safe area** → [04](04-identidade.md). A
  medição já decidiu que o acento não vai sobre a foto e que contraste ruim se
  conserta escurecendo o fundo, não clareando a letra.
- **Casar duas tomadas por correlação** → [03](03-sincronismo-multipista.md). A
  correlação global falha em música repetitiva, e falha mentindo: acha pico
  convincente em qualquer lugar.
- **Qualquer coisa em `importado/`** → [02](02-import-video-use.md).

## Numeração

Os números dizem a ordem em que os documentos apareceram, não prioridade. O
`07` nasceu como um segundo `06` — colisão corrigida em 11/09/2026, sem
referências a atualizar. Documento novo pega o próximo número livre.
