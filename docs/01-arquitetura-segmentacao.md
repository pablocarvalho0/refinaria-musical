# Arquitetura de segmentação: fala e música

Status: **passos 1 e 2 feitos e medidos** (24/08/2026). Passos 3 e 4 sem medição.
Supera a abordagem defensiva descrita no CLAUDE.md ("a transcrição diz onde não cortar").

## A ideia

A transcrição não serve só para proteger a música do corte. Ela **particiona o vídeo em
duas classes de conteúdo**, e cada classe pede um tratamento próprio.

Onde o Whisper produziu texto, é fala. Onde não produziu, é instrumento. Essa fronteira sai
de graça do que já rodamos — não exige modelo novo, detecção de onset, nem classificador.

O que era uma regra ("não cortar aqui") vira estrutura ("processar isto de outro jeito").

## Por que isso muda o pipeline

Hoje todo o vídeo recebe o mesmo tratamento, e cada parâmetro é um compromisso ruim entre
duas necessidades opostas:

| Dimensão | Região FALA | Região MÚSICA | Hoje |
|---|---|---|---|
| Denoise | agressivo — inteligibilidade importa | nenhum — destrói ataque e harmônicos | meio-termo que serve mal aos dois |
| Compressão | forte, nivela a voz | leve ou nenhuma, dinâmica é conteúdo | achata o violão |
| Loudness | −14 LUFS | preservar transiente | limitador atua nos picos de ataque |
| Corte | seco, remove hesitação e take ruim | intocável | risco de picotar a música |
| Enquadramento vertical | mira o rosto | mira o braço do violão | crop único, sempre errado para um dos dois |
| Overlay de cifra/pauta | atrapalha | é exatamente onde deve entrar | sem critério |

Com a segmentação, cada coluna vira uma cadeia de processamento independente, aplicada ao
seu próprio intervalo, e no fim os segmentos são reunidos.

## Fluxo proposto

```
master 4K
   ↓ normaliza
1080p60 + wav
   ↓ transcreve
transcrição com timestamps
   ↓ classifica
segmentos.txt  →  [FALA 00:00:04–00:00:37]
                  [MUSICA 00:00:37–00:03:09]
   ↓ processa por classe
segmentos de fala  (denoise + compressão + corte)
segmentos de música (normalização suave, sem corte)
   ↓ concat
vídeo final
```

## Pré-requisito técnico

Emendar segmentos processados separadamente exige que **todos os parâmetros de saída
batam exatamente**: resolução, frame rate, pixel format, sample rate, layout de canais e
perfil de encode. Divergência em qualquer um deles faz o `concat` recusar ou produzir
dessincronia progressiva.

Por isso a padronização já feita deixa de ser higiene e vira requisito:

- `-r 60` (CFR)
- `-ar 48000`
- `-pix_fmt yuv420p`
- `1920x1080`

Qualquer cadeia nova precisa terminar nesses valores.

## Hipótese a validar antes de construir

A fronteira que o Whisper entrega **não é limpa**, e o tamanho da zona cinzenta determina
se essa arquitetura é viável ou frágil.

Casos que quebram a classificação binária:

1. **Fala sobre a música** — comentar enquanto toca. Pertence às duas classes.
2. **Nota sustentada decaindo** dentro de uma pausa de fala.
3. **Contagem e vocalização** ("um, dois, três, quatro") — o Whisper transcreve, mas é
   parte da performance.
4. **Gaps curtos** entre segmentos de fala: silêncio real ou música baixa?
5. **Alucinação do Whisper** em trechos sem fala, gerando texto onde há só instrumento.

### Medição proposta

Rodar sobre um episódio real e reportar:

- Duração total classificada como FALA e como MUSICA
- Número e duração dos gaps não cobertos por nenhum segmento de transcrição
- Segmentos de fala com menos de 2s isolados dentro de região musical
- Energia RMS média nas regiões classificadas como MUSICA — se for baixa, é silêncio
  mal rotulado, não música

**Critério de decisão:** se a zona cinzenta ficar abaixo de ~10% da duração, a arquitetura
se sustenta com uma regra de desempate simples. Acima disso, vale considerar um sinal
complementar (energia, ou detecção de pitch estável) em vez de depender só da transcrição.

## Mitigação pela gravação

Boa parte da ambiguidade some com disciplina de captura, que é mais barata que qualquer
algoritmo:

- **Falar antes e depois de tocar.** "Vou tocar o exemplo" … toca … "repara no baixo".
  Cria fronteira explícita no texto em vez de inferida pela ausência.
- **Não comentar por cima da execução.** Separar em dois momentos.
- **Falar o nome do acorde** antes de tocá-lo, não durante.

## Ganhos esperados

- Áudio de fala inteligível **e** violão com timbre preservado, no mesmo arquivo
- Corte agressivo onde ele ajuda, zero corte onde ele destrói
- Base para reenquadramento vertical automático por classe
- Base para overlay de pauta e cifra no intervalo correto

## Ordem de implementação

1. Gerar `segmentos.txt` a partir da transcrição e **medir a zona cinzenta** (acima)
2. Só então: cadeias de áudio separadas por classe
3. Depois: corte aplicado apenas às regiões de fala
4. Por último: crop vertical e overlay por classe

Não avançar para 2 sem o resultado de 1.

---

## Resultado da medição — 24/08/2026

Passo 1 executado. Episódio `20260824_135542`, 189,589s, modelo `small`, `vad_filter=True`.
Reprodutível com `python scripts/segmenta.py work/<base>.wav`; saída em `work/segmentos.txt`.

### Métricas pedidas

| Métrica | Valor |
|---|---|
| FALA | 34,000s — 17,9% — 1 região |
| MUSICA | 155,589s — 82,1% — 2 regiões |
| Gaps não cobertos | 2 (154,449s + 1,140s) |
| Gaps abaixo de 2s | 1 (1,140s, cabeça do arquivo) |
| Fala < 2s isolada em música | nenhuma |
| RMS agregado nas regiões MUSICA | −15,4 dBFS |
| Regiões MUSICA abaixo de −50 dBFS | nenhuma |

**Zona cinzenta: 5,600s = 3,0% da duração. Abaixo do critério de ~10%.**

### Por que o número sozinho engana

As métricas da lista original olham a transcrição olhando para si mesma. O `faster-whisper`
devolve segmentos **encostados uns nos outros** — de 1,140s a 35,140s não existe um único
buraco. Sem buraco não há gap para contar, e a fronteira parece limpa por construção.

O que decide a viabilidade é outra coisa: **onde a fronteira cai e com que precisão.**

Confrontando o rótulo com a energia do áudio em janelas de 100ms (piso de atividade
−35 dBFS):

- 6,00s rotulados FALA estão mudos — pausas dentro da fala (17,6% da região)
- 18,10s rotulados MUSICA estão mudos — respiros entre frases musicais (11,6% da região)
- desacordo total: 24,10s = **12,7% da duração**

Esse desacordo **não invalida a arquitetura**: um respiro de 1s dentro da música continua
indo para a cadeia de música, que é o tratamento certo. O erro que custa é outro — conteúdo
roteado para a cadeia errada, e isso só acontece na fronteira.

### A medição que importa

Da fronteira FALA→MUSICA em 00:00:35.140, a energia leva **4,46s** para assentar acima do
piso de atividade. Entre 35,9–37,0s e 39,0–39,6s há trechos praticamente mudos, e entre eles
picos de −16 dBFS. A transcrição parou em 35,140s; o áudio não corrobora esse ponto.

A fronteira MUSICA→FALA em 00:00:01.140 não é medível por esse critério — fala é
intermitente por natureza, e exigir 3s contínuos acima do piso mediria o ritmo do falante,
não ambiguidade.

### Conclusão

**A arquitetura se sustenta neste episódio, e a amostra não autoriza generalizar.**

Este episódio é o caso favorável extremo: fala corrida por 35s, depois violão por 154s —
exatamente a "mitigação pela gravação" descrita acima, aplicada sem querer. Ele tem **uma
única fronteira medível**. n=1.

O custo da ambiguidade é **por fronteira, não por minuto**. A 4,46s por fronteira, o
orçamento de 10% de 189,6s cabe em 4,3 fronteiras:

> **Regra derivada:** a segmentação só por transcrição se sustenta enquanto a alternância
> fala/música for **mais espaçada que ~45s**. Uma aula de harmonia que diz "ouve esse
> acorde" → toca 8s → "percebeu a sétima?" → toca 6s estoura o critério com folga.

### Antes de avançar para o passo 2

1. Medir mais 2–3 episódios, escolhidos com alternância real — este não exercitou nenhum
   dos cinco casos de quebra listados acima.
2. Adotar o sinal complementar barato (abaixo) e remedir.

### Sinal complementar mais barato

Não é energia. Energia separa som de silêncio, e tanto voz quanto violão estão a −15 dBFS —
ela não decide qual dos dois é. O sinal mais barato vem de trabalho que **já está sendo
feito**, sem modelo novo nem dependência nova:

1. **`word_timestamps=True` no `transcribe`.** Troca a fronteira de nível de segmento
   (preenchida e quantizada — repare que todo timestamp deste episódio termina em `.140`)
   por nível de palavra, com precisão de dezenas de ms. Ataca direto o borrão de 4,46s.
   Custo: uma flag, alinhamento por cross-attention no mesmo modelo já carregado.

2. **`faster_whisper.vad.get_speech_timestamps`.** O Silero VAD **já roda** a cada
   transcrição por causa do `vad_filter=True`; hoje o resultado é descartado. Expor esses
   intervalos dá uma decisão fala/não-fala independente do texto — o que pega justamente
   os casos 1 (fala sobre música) e 5 (alucinação), onde texto e acústica discordam.

Fazer os dois e cruzar: onde palavra, VAD e energia concordam, a fronteira é firme; onde
discordam, é zona cinzenta explícita, e aí a regra de desempate tem em que se apoiar.
Detecção de pitch estável só se isso não bastar.


---

## Resultado do passo 1, remedido com large-v3 — 24/08/2026

O episódio `20260824_135542` e o `ep00` desta execução são **o mesmo arquivo**
(`inbox/video_0.mp4`, 189,62s). A remedição troca só o modelo de transcrição.

| Métrica | `small` | `large-v3` |
|---|---|---|
| FALA | 34,000s (17,9%) | 33,460s (17,6%) |
| MUSICA | 155,589s (82,1%) | 156,129s (82,4%) |
| Fim da fala | 00:00:35,140 | 00:00:34,600 |
| Ambiguidade na fronteira | 4,46s | **5,00s** |
| Zona cinzenta | 3,0% | **3,2%** |
| Orçamento de 10% | 4,3 fronteiras | 3,8 fronteiras |
| Espaçamento mínimo | ~45s | **~50s** |

**O modelo maior não melhorou a fronteira — piorou.** Ele termina a fala 0,54s
antes, e o áudio leva ainda mais tempo para assentar depois desse ponto. Isso
reforça o diagnóstico do passo 1: o problema da fronteira não é qualidade de
reconhecimento, é que a transcrição não sabe onde a música começa. Trocar de
modelo não ataca a causa; `word_timestamps` e o VAD do Silero atacam.

Custo de transcrição, large-v3 `int8_float16` na GTX 1650: **8,6s de inferência
para 189,6s de áudio** (0,045x tempo real), pico de **2278 MiB de 4096** de VRAM.
Não houve OOM e não foi preciso cair para `medium`. Carga do modelo: 4,9s.

## Resultado do passo 2 — 24/08/2026

Implementado em `scripts/audio.sh`. Números completos e decisões de implementação
em `CLAUDE.md`, seção "Tratamento de áudio por classe". Resumo:

- A tabela de compromissos ruins deste documento previa três problemas do
  tratamento uniforme: compressão que "achata o violão", loudness que faz o
  limitador atuar nos picos de ataque, e denoise que serve mal aos dois. Os dois
  primeiros foram **medidos e confirmados**: o `loudnorm` uniforme movimenta o
  ganho em **9,09 dB** ao longo da região musical, e deixa a fala 2,9 dB abaixo
  da música.
- Com as cadeias separadas, o ganho na música varia **0,08 dB** e as duas classes
  ficam a 0,09 dB uma da outra, ambas em −14 LUFS.
- A emenda entre as cadeias foi resolvida por **máscara com rampa**, não por
  concat. As duas máscaras somam 1,000000 em todas as amostras. Isso torna o
  pré-requisito de "todos os parâmetros de saída baterem exatamente" **irrelevante
  para o áudio** — não há concat de áudio. Ele continua valendo para o vídeo,
  quando os passos 3 e 4 chegarem.

### O que o passo 2 revelou e o documento não previa

1. **Desalinhamento entre master e `_norm`.** 21,33 ms — 1024 samples, o atraso
   do codificador AAC. Qualquer passo que misture áudio de uma fonte com vídeo de
   outra precisa medir isso, não supor zero.
2. **Latência de filtro.** O `afftdn` atrasa 25,00 ms. Duas cadeias paralelas com
   latências diferentes desalinham entre si.
3. **`linear=true` não vale para a fala.** Ela precisa de +7,00 dB, o que estoura
   o teto de true peak, e o `loudnorm` volta ao modo dinâmico.
4. **O áudio tratado transcreve pior.** 92,5% de similaridade contra o `_norm`,
   três trechos degradados, nenhum melhorado. A transcrição tem que sair do
   `_norm`. Isso amarra a ordem do pipeline: transcrever **antes** de tratar.


---

## Reestruturação do pipeline — 24/08/2026 (v3)

A medição do passo 2 expôs que o `processa.sh` e o `audio.sh` disputavam a mesma
responsabilidade. A divisão foi refeita: **`processa.sh` cuida do vídeo,
`audio.sh` cuida do áudio, e não se sobrepõem.**

O efeito colateral relevante para *este* documento é que a transcrição passou a
sair do áudio cru, e isso **melhorou a segmentação mais do que qualquer coisa
tentada até aqui**:

| | fronteira FALA→MUSICA | ambiguidade | zona cinzenta |
|---|---|---|---|
| transcrito do `_norm` (`loudnorm`) | 00:00:34,600 | 5,00s | 3,2% |
| transcrito do áudio cru | 00:00:37,610 | **1,99s** | **1,7%** |

O `loudnorm` de passo único é dinâmico: ele levanta os trechos quietos. No fim
da fala, isso levantava o ruído de sala o bastante para o Silero VAD decidir que
a fala tinha acabado 3s antes do que acabou. **Normalizar antes de transcrever
degradava a fronteira** — o oposto da intuição.

### A regra de desempate, implementada

O documento previa que a arquitetura se sustentaria "com uma regra de desempate
simples". Ela é: **fundir regiões de fala separadas por menos de 2s**
(`funde_curtos` em `segmenta.py`).

Sem ela, o áudio cru sai pior que o normalizado (7,2% contra 3,2%), porque o
Whisper abre um buraco de 1s no meio de uma fala corrida e esse buraco vira uma
ilha de MUSICA com duas fronteiras novas. Como o custo é por fronteira, duas
fronteiras falsas custam mais que o buraco vale.

Mandar 1s de pausa para a cadeia de fala é inofensivo mesmo se for música. O
inverso — uma ilha de música dentro da fala — custa duas rampas e dois pontos
de decisão. A assimetria é o que justifica a regra.

### Consequência para a regra derivada

Com 1,99s de ambiguidade por fronteira, o orçamento de 10% cabe em **9,5
fronteiras**: uma alternância fala/música a cada **~20s**, contra os ~45–50s das
medições anteriores. A aula de harmonia que diz "ouve esse acorde" → toca 8s →
"percebeu a sétima?" continua fora do orçamento, mas a margem triplicou.

Segue valendo: **n=1**, uma fronteira medível, caso favorável extremo. Os quatro
números desta série vêm do mesmo arquivo.
