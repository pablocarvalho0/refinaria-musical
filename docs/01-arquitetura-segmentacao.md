# Arquitetura de segmentação: fala e música

Status: **proposta** — validar a hipótese antes de implementar.
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
