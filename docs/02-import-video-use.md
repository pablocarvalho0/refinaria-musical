# Import do browser-use/video-use — em validação

**Decidido em 30/08/2026.** Registro de uma importação parcial e sob teste.
Enquanto este documento disser "em validação", nada da pasta `importado/`
faz parte do fluxo oficial do `CLAUDE.md`.

## O que é a origem

| | |
|---|---|
| Repo | https://github.com/browser-use/video-use |
| Commit avaliado | `9575612f066aa517354790a645fd90f9f95a743b` (30/08/2026) |
| Licença | MIT — cópia em `importado/video-use/LICENSE-upstream` |
| Tamanho | ~1500 linhas de Python em `helpers/` + `SKILL.md` de 23 KB |

É a mesma tese central deste projeto — a transcrição é a superfície que o
LLM lê, em vez de assistir ao vídeo — empacotada como skill de agente.
Convergência independente, o que é um bom sinal para a arquitetura.

## O regime de trabalho

**Pasta separada, integração só depois de validado.** O código importado
vive em `importado/video-use/`, fora de `scripts/`. Um item só migra para
`scripts/` quando o critério de validação dele estiver cumprido e medido
neste documento. Até lá, `importado/` é área de teste e pode quebrar.

Motivo: as decisões deste projeto vieram de medição, e o video-use traz
uma premissa que já medimos e descartamos (corte por silêncio). Misturar
os dois códigos antes de testar apagaria a fronteira entre o que foi
medido aqui e o que foi herdado de fora.

**O `SKILL.md` deles não é registrado como skill.** Ele tem 12 regras duras
que conflitam de frente com o `CLAUDE.md` — exige ASR da ElevenLabs, manda
tirar cortes de silêncios ≥400 ms, impõe outra estrutura de diretórios.
Duas fontes da verdade brigando em contexto é pior que nenhuma. As ideias
boas dele entram como texto neste documento, não como skill carregada.

## O que foi importado

### 1. `timeline.py` — filmstrip + onda + palavras numa PNG ✅ portado, ⏳ em validação

Porte de `helpers/timeline_view.py`. Condensa um intervalo do vídeo numa
imagem estática: N frames em miniatura, envelope RMS do áudio, rótulos de
palavra e as regiões de FALA/MÚSICA sombreadas.

Resolve um problema real: o princípio 2 proíbe subir mídia para o chat, e
até agora isso significava que ninguém olhava o vídeo antes de decidir.
Uma PNG de ~290 KB e 1920x570 cabe no chat e mostra 11 segundos.

Três mudanças de mérito em relação ao upstream:

- **Lê o nosso `.words.tsv`** em vez do JSON da ElevenLabs Scribe.
- **Sombreia por classe, não por silêncio.** O upstream pinta todo gap de
  ≥400 ms como candidato a corte; aqui o sombreado vem do `segmentos.txt`.
- **Cor da palavra pela probabilidade.** A coluna `prob` do nosso sidecar
  não existe na Scribe. Abaixo de 0,60 a palavra sai laranja.

Custo medido: **2,9s** para uma janela de 11s com 10 frames, no `ep00`.
Dependência nova: `Pillow` (12.3.0, instalado no venv). O `librosa` do
upstream não foi importado — o fallback por ffmpeg já resolve.

### Achado 1 — "dentro da FALA" não basta como guarda

Na primeira execução o porte marcou **2,38s de violão** (34,71–37,09s)
como candidato a corte. As regiões do `segmentos.txt` são grossas — o
`ep00` tem três para 189s — então "dentro da FALA" ainda contém violão
entre as frases. Sem guarda extra, o porte reproduzia exatamente o erro do
auto-editor que este projeto descartou.

Guarda adicionada: o gap também precisa estar **abaixo de −25 dB em
relação ao pico da janela**. Medido em todos os gaps ≥0,4s da região de
fala do `ep00`:

| Gap | Duração | Energia (dB rel. pico) | Vira candidato? |
|---|---|---|---|
| 3,57–4,63 | 1,06s | −13,2 | não |
| 13,55–13,99 | 0,44s | −11,3 | não |
| 30,17–31,17 | 1,00s | −5,9 | não |
| 34,71–37,09 | 2,38s | −15,8 | não |

**Os quatro gaps de silêncio do episódio estão musicalmente ocupados.** A
heurística do video-use teria produzido 4 candidatos a corte e os 4 estão
errados — 100% de falso positivo em n=4. É a confirmação empírica mais
direta que este projeto tem da decisão de remover o auto-editor.

Ressalva honesta: **o limiar de −25 dB nunca disparou positivo**, porque
não há silêncio verdadeiro no `ep00`. Está calibrado só pelo lado da
rejeição, com 9,2 dB de folga sobre o gap mais silencioso observado.
Precisa de um episódio com pausa seca para ser validado dos dois lados.

## Fila — importar depois, na ordem

### 2. Auto-avaliação do render nas emendas ⏳ não começado

O passo 7 do processo deles roda o `timeline_view` no **output renderizado**
em cada emenda de corte, procurando salto visual, pico de forma de onda
(pop que passou pelo fade) e legenda escondida atrás de overlay. Só mostra
o preview depois de passar, com teto de 3 tentativas.

Nós validamos o `corta.sh` uma vez, à mão, em 24/08/2026. Isto viraria
rotina barata em cima do item 1, que já está portado.

### 3. Regras de ordem da cadeia de filtros ⏳ não começado — texto, não código

Valem para os passos 3 e 4 da segmentação (crop vertical + overlay), que
ainda não existem:

- **Legenda por último**, depois de todo overlay. Caso contrário o overlay
  cobre a legenda, e a falha é silenciosa.
- **Extrair por segmento e concatenar com `-c copy`**, em vez de um
  filtergraph de passo único — senão cada segmento leva geração dupla
  quando entram overlays.
- **Overlay com `setpts=PTS-STARTPTS+T/TB`**, para o frame 0 do overlay
  cair no início da janela dele.
- **Offset de SRT na timeline de saída**: `saida = palavra.inicio −
  segmento.inicio + segmento.offset`.
- **`afade` de 30 ms em toda emenda.** Nós medimos que no `ep00` não há
  transiente na emenda (pico desce −19,0 → −21,3 → −21,9 dBFS), mas foi um
  caso. A rede é barata.

### 4. Margem da legenda no vertical ⏳ não medido — o único item que afeta o que já está pronto

Eles fixam `MarginV=90` sobre `PlayResY=288`, ou seja **~31% da altura**,
e justificam: a UI de Reels/Shorts/TikTok (legenda, usuário, música,
barra de ações à direita) cobre os ~25–30% inferiores do quadro.

O nosso `.ass` tem `MarginV=90` sobre `PlayResY=1080` — **8,3%**. Se a
afirmação deles proceder, nossa legenda está dentro da faixa que o app
cobre. Nunca testamos no app.

**Como medir:** subir um vertical de teste, tirar print da tela do app e
comparar onde a legenda cai em relação à UI. Não dá para decidir isso no
ffmpeg.

## Recusado — e por quê

| Item | Motivo |
|---|---|
| ElevenLabs Scribe | API paga e sobe o áudio para a nuvem. O `faster-whisper large-v3` local já está medido, e o achado de transcrever do áudio cru (zona cinzenta 3,2% → 1,7%) é nosso, não está lá. |
| `render.py` inteiro | Reescala tudo para 1920 e reencoda com `-c:a aac 192k`, sem `loudnorm`. Adotar jogaria fora o áudio por classe do `audio.sh`. As regras de ordem dele entram como item 3; o código, não. |
| Corte por gap de silêncio | Já medido e descartado aqui. O achado 1 acima re-confirma com números novos. |
| Animações (HyperFrames / Remotion / Manim) | Fora de escopo para violão + fala. |
| Diarização de falantes | Operação solo, um falante. |
| Sub-agentes paralelos por animação | Depende das animações. |
| `grade.py` (color grading automático) | Não avaliado. Grade automático **por segmento** tende a variar entre cortes e criar salto visual. Se voltar à mesa, vem com forma de medir a variação entre segmentos. |

## Critério de conclusão

O import está encerrado quando cada item da fila estiver ou migrado para
`scripts/` com medição registrada, ou recusado com motivo escrito. Aí este
documento vira registro histórico e a pasta `importado/` some.
