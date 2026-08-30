# Sincronismo de múltiplas tomadas

Registro do que foi medido em 30/08/2026 sincronizando gravações separadas da
mesma música, em dois projetos fora deste repositório: `~/Music/Projetos/
like-a-stone` (três overdubs de violão, mix no Audacity) e
`~/Music/Projetos/oficina-g3` (violão + bateria, sem projeto de DAW).

Os dois casos têm o mesmo formato — "estas gravações são a mesma música, case
elas" — e resposta oposta. A diferença entre eles é a lição principal.

## A regra: procure a medida antes de estimar o sinal

No `like-a-stone` o sincronismo **já estava gravado**. O `.aup3` do Audacity é
um SQLite cuja tabela `project` guarda a timeline em XML binário, e o atributo
`offset` de cada `<waveclip>` é o deslocamento exato de cada tomada. Não
precisou de estimativa: bastou ler. A correlação cruzada entrou depois, como
segunda opinião, e bateu dentro de **1 amostra**.

No `oficina-g3` não havia projeto de DAW — só dois `.m4a`. Aí sim foi preciso
medir no sinal, e é onde mora a armadilha.

É o mesmo padrão de `docs/02-import-video-use.md`, onde os gaps de silêncio do
`ep00` foram julgados pelo conteúdo musical e não pela energia: **preferir o
dado que já existe à heurística sobre o sinal.**

## A armadilha: correlação global mente em música repetitiva

Correlação cruzada da faixa inteira é o instinto óbvio e **falha de um jeito
que engana**. Medido no `oficina-g3`, janelas de 4 s da base procuradas na
bateria inteira:

| janela | lag encontrado | razão pico/mediana |
|---|---|---|
| 5,6 s | −12,683 s | 10,06 |
| 7,6 s | −6,443 s | 9,91 |
| 9,6 s | −11,371 s | 11,87 |
| 19,6 s | −17,877 s | 13,35 |

23 janelas de 23 com pico "confiável", e o lag saltando entre −6,4 s e
−17,9 s. Música repetitiva casa consigo mesma a cada compasso, então a
correlação sempre acha um pico convincente — em qualquer lugar. **A razão
pico/ruído não detecta esse erro**, porque o pico é genuíno; ele só não é o
pico certo.

Os dez melhores candidatos globais ficavam espaçados por ~0,184 s, exatamente
a semicolcheia da base. A correlação sabia a *grade*; não sabia o *compasso*.

Um segundo teste confirmou: varrendo lag × razão de andamento (0,990 a 1,010),
o casamento de onsets deu escores entre 0,036 e 0,045 para **todas** as
combinações. Quando nenhuma hipótese se destaca, não há sinal — há ruído com
um vencedor arbitrário.

## O que funciona: ancorar numa passagem curta, depois verificar

A pista que resolveu não veio do sinal, veio do autor: *"no início existem 4
batidas fortes do riff principal que sincronizam com a bateria"*.

| | 1ª | 2ª | 3ª | 4ª |
|---|---|---|---|---|
| Base | 5,740 s | 5,980 s | 6,240 s | 6,480 s |
| Drum | 4,840 s | 5,120 s | 5,380 s | 5,600 s |
| diferença | 900 ms | 860 ms | 860 ms | 880 ms |

Média 875 ms, desvio 17 ms. A correlação de envelope restrita a essa janela,
com resolução de 1 ms, deu **858,2 ms**, e — decisivo — o segundo candidato
ficou a **64% do melhor**. Essa separação é o que a correlação global nunca
teve, e é o número que se deve olhar para decidir se a medida vale.

**Correlacionar envelope de ataque, não forma de onda.** Timbre é o que separa
violão de bateria; ataque é o que eles têm em comum. A medida usa a derivada
positiva do envelope de pico, com resolução de 1 ms. Correlacionar forma de
onda entre instrumentos diferentes não funciona.

**Sempre medir a deriva depois.** Um offset ancorado no início pode não valer
para o resto. O diagnóstico distingue dois casos:

- **deriva acumulada** (tendência monotônica): offset fixo não segura a faixa;
  precisa de time-stretch ou de alinhamento elástico com âncoras múltiplas.
- **flutuação sem tendência**: as duas performances oscilam em torno do mesmo
  andamento médio; offset fixo serve para a faixa inteira.

No `oficina-g3` a tendência ao longo de 50 s foi de **+47 ms** — ruído. Cada
faixa flutua ±2% de andamento por conta própria (base 161–167 BPM, bateria
161–167 BPM), mas nenhuma escapa da outra. Offset fixo bastou, sem esticar
áudio.

## A conferência é ouvir os dois separados

A soma esconde erro de sincronismo: dois ataques a 80 ms de distância viram um
ataque gordo, não dois. Com as fontes em canais opostos — uma à esquerda, a
outra à direita — o encaixe fica audível. É a saída `_conferencia_LR.m4a` do
`mixa-alinhado.sh`, e é o arquivo que se deve ouvir primeiro.

O equivalente no `like-a-stone` é o `verifica-sinc.py`, que mede o desvio de
cada segmento montado contra o mix: a v3 fechou com pior desvio de 0,12 ms.

## Ferramentas

Em `scripts/`, servem para qualquer par de gravações:

```bash
cd ~/video && source .venv/bin/activate
python scripts/alinha-faixas.py REFERENCIA.wav OUTRA.wav   # WAV mono 48 kHz
./scripts/mixa-alinhado.sh REFERENCIA OUTRA OFFSET_MS [PREFIXO]
```

O `alinha-faixas.py` imprime o offset, a separação do segundo candidato e o
diagnóstico de deriva. O `mixa-alinhado.sh` aplica o offset e gera três
arquivos: o mix normalizado, o mix com dinâmica intacta, e a conferência L/R.

Ambos usam só `numpy` e a stdlib — a análise é FFT, envelope e autocorrelação,
e não justifica instalar `scipy` nem `librosa` no venv.

## Armadilhas de ffmpeg encontradas no caminho

**`amerge` embaralha canais** quando os dois lados são mono sem layout
declarado. O aviso é `Input channel layouts overlap` e o resultado sai errado
em silêncio: o canal esquerdo tinha som em 0,4 s num arquivo onde a base só
começa em 5,7 s. Usar `join=inputs=2:channel_layout=stereo`.

**Fonte que já vem com pico em 0 dBFS não aceita ganho positivo.** A bateria
do `oficina-g3` tinha true peak +0,1 dBFS. Todos os ganhos do mix são
negativos e o nível é recuperado só na normalização final.

**Crest factor alto não sobrevive a −14 LUFS.** O mix cru tinha −26,4 LUFS com
pico −4,2 dBTP: 22 dB de crest, normal para acústico sem compressão. Chegar a
−14 exige +12,4 dB, e o `loudnorm` volta ao modo dinâmico — o LRA cai de 4,5
para 3,6. Testado trocar por ganho estático + `alimiter`, e ficou **pior**
(−15,5 LUFS, LRA 3,5). Por isso o script entrega as duas versões: a
normalizada para ouvir, a de dinâmica intacta para masterizar depois.

É o mesmo achado de "Tratamento de áudio por classe" no `CLAUDE.md`, por outro
caminho: `loudnorm` de passo único é dinâmico e anda em cima do material.

## Da montagem: adicionar em vez de trocar

Lição de edição, não de medição, mas vale registrar porque custou três
iterações no `like-a-stone`.

Quando uma das tomadas é a melhor visualmente, ela **não deve sair da tela no
primeiro corte**. O roteiro original trocava para tela cheia na tomada nova no
instante em que o solo entrava, largando justamente o vídeo em que o violão
ficava melhor de ver. A correção foi empilhar em vez de trocar: a base fica em
cima e o solo entra embaixo.

O que tornou as três iterações baratas foi a forma, não a sorte:

- **O roteiro é um TSV editável**, e o script o executa. Trocar o layout é
  editar uma linha, não refazer a montagem à mão.
- **Cada variação vai para um destino próprio**, nunca sobrescrevendo a
  anterior. Comparar exige ter as duas.
- **A grade é em frames, não em segundos.** Cada segmento roda com
  `-frames:v` exato e a soma é conferida contra o total do projeto (1523).
  Sem isso os arredondamentos por trecho acumulam e a soma não fecha.

O detalhe de enquadramento que generaliza: nas tomadas de celular o rosto fica
na metade de cima do quadro e o violão na de baixo, então um recorte central
corta os dois pela metade. O painel precisa de uma janela por fonte (`y` e
`h`), e a tomada em que o violão aparece só na borda inferior precisa de zoom
para o painel não sair torso.

## O que não foi feito

**Alinhamento elástico** (âncoras múltiplas + stretch por trecho, o
equivalente a warp markers de DAW). Não foi necessário porque não havia deriva
acumulada, e esticar áudio custa qualidade. Se algum dia uma dupla de
gravações mostrar tendência monotônica no diagnóstico do `alinha-faixas.py`,
é esse o caminho.
