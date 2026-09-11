# ep00 — sonorização e plano de edição

Medido em 05/09/2026. O ep00 (= `inbox/video_0.mp4`, 189,6 s) é o episódio de
apresentação: 35,6 s de fala de teste com o celular na mão, e 152,2 s de
improviso de violão em plano fixo.

Estado: **áudio pronto**, edição de imagem proposta e não executada.

## O que ficou feito

`out/ep00/ep00_audio.mp4` — 1920x1080, 60 fps CFR, 189,616667 s, AAC 48 kHz
`language=por`, uma geração de AAC.

| | v1 (24/08, `audio.sh` puro) | **novo (violão com reverb)** | alvo |
|---|---|---|---|
| I total | −14,01 | **−14,11** | −14 LUFS |
| I fala | −14,31 | **−14,46** | −14 |
| I música | −13,97 | **−14,05** | −14 |
| desnível fala/música | 0,34 dB | **0,41 dB** | ~0 |
| true peak | −1,35 | **−1,40** | ≤ −1 dBTP |
| LRA música | 7,40 | **4,80** | preservar |

A última linha é o único desvio, e é do **rider**, não do reverb — ver abaixo.

O `_audio.mp4` de 24/08 foi preservado como `ep00_audio.v1.mp4`: é a versão
medida na tabela "Tratamento de áudio por classe" do `CLAUDE.md`.

### Como reproduzir

```bash
cd ~/video && source .venv/bin/activate

# 0. o master é video_0.mp4, mas o projeto é ep00 — o symlink resolve o nome
#    sem tocar no inbox (Receive Only) e sem gastar disco
ln -sfn ../inbox/video_0.mp4 work/ep00.mp4
./scripts/processa.sh work/ep00.mp4          # -> out/ep00/ep00_norm.mp4

# 1. o violão tratado. --inicio é 37,360 e NÃO 37,410: 50 ms antes da
#    fronteira, para o WAV cobrir a rampa da máscara — ver "a janela" abaixo
./scripts/violao.sh out/ep00/ep00_norm.mp4 \
    --inicio 37.360 --duracao 152.256 --lufs -14 --tp -1.5 \
    --saida work/ep00_violao.wav

# 2. o entregável: fala pela cadeia do audio.sh, música pelo WAV
MUSICA_WAV=work/ep00_violao.wav MUSICA_OFFSET=37.360 \
    ./scripts/audio.sh out/ep00/ep00_norm.mp4
```

Verificado depois: áudio do `_norm` **bit-idêntico** ao do master (MD5
`497028d9…`), alinhamento contra o `.wav` da transcrição **0,00 ms**, e o
violão dentro do MP4 final a **lag 0 amostras, r = 0,9999** contra o WAV.

## O `audio.sh` ganhou `MUSICA_WAV`

A cadeia de MÚSICA do `audio.sh` é um `loudnorm` e nada mais; violão solo pede
reverb e um ganho lento em vez de compressor, e isso vive no `violao_dsp.py`,
em Python. Não há como pôr convolução dentro daquele filtergraph.

A alternativa era um script novo que refizesse a cadeia de fala e a máscara.
Foi descartada: duplicaria o `loudnorm` de dois passos e a máscara trapezoidal,
e o `CLAUDE.md` fixou na v3 que **o `audio.sh` é o único produtor de áudio**.
Em vez disso o ramo de música passou a poder vir de fora, pronto:

```bash
MUSICA_WAV=<wav já tratado> MUSICA_OFFSET=<s> ./scripts/audio.sh <_norm.mp4>
```

O WAV entra sem `loudnorm` nenhum — normalizar de novo desfaria o rider. O
script confere que está a 48 kHz e imprime a duração.

### A janela, e o defeito que ela consertou

Primeira tentativa: o ramo de música virou `[1:a]adelay=…` e nada mais. O
entregável saiu com **1,785 s absolutamente mudos no começo**, sem erro nem
aviso.

Causa: o `segmentos.txt` do ep00 classifica **0 → 1,790 s como MÚSICA** (o
autor ajustando o celular antes de falar), e o WAV do violão só começa em
37,410 s. A máscara pedia o ramo de música onde o `adelay` só tinha zeros.

É o modo de falha que este projeto mais persegue — arquivo íntegro, código de
saída 0, só se percebe ouvindo. E não é específico do ep00: **qualquer** região
de MÚSICA fora do trecho tratado cai nele.

A correção é uma **janela**: a máscara de música é multiplicada por um trapézio
que vale 1 de `offset` a `offset+dur`. Fora dela a música vale 0 e a fala vale
1, então o trecho herda a cadeia de fala — que é cadeia legítima. As duas
máscaras continuam somando exatamente 1 em todo ponto, que é a propriedade
medida que sustenta a rampa.

**A rampa da janela sobe ANTES do offset, não depois.** Assim, na fronteira
FALA→MÚSICA a janela já vale 1 e o crossfade fica inteiro por conta da máscara
de fala, como sempre foi. É isso que obriga o WAV a começar `RAMPA` segundos
antes da fronteira — daí `--inicio 37.360` para uma fronteira em 37,410.

Conferido depois da correção: **18 janelas de 5 ms com pico abaixo de −100 dBFS,
todas em 0,000–0,090 s** — o offset do stream de áudio do celular (0,048896 s),
que o `v1` também tem. Nenhum outro ponto mudo em 189,6 s. Na fronteira, o RMS
desce de −16,0 a −31,9 dBFS e volta: é a pausa real entre o "Show!" e a primeira
nota, não um buraco.

## O rider custa 2,92 LU neste episódio, e o reverb custa zero

O `CLAUDE.md` tem "LRA música: preservar" como critério (master 8,60; `audio.sh`
8,50). O entregável saiu com 4,80. Medido de onde vem, no mesmo trecho:

| configuração | LRA | TP |
|---|---|---|
| rider 3 + reverb (padrão) | **4,79** | −1,50 |
| rider 0 + reverb | **7,71** | −2,83 |
| rider 3, sem reverb | 4,48 | −1,50 |
| rider 0, sem reverb | 7,30 | −3,16 |

**O reverb não achata — ele até alarga um pouco** (+0,31 a +0,41 LU,
preenchendo os vales). Os 2,92 LU são todos do rider, que **saturou no teto**
(ganho aplicado de −1,95 a +3,00 dB).

Grade completa:

| teto do rider | LRA | TP | ganho aplicado |
|---|---|---|---|
| 0 | 7,71 | −2,83 | — |
| 1 | 6,19 | −2,33 | −1,00 a +1,00 |
| 1,5 | 5,76 | −2,10 | −1,47 a +1,50 |
| 2 | 5,37 | −1,94 | −1,82 a +2,00 |
| 2,5 | 5,08 | −1,70 | −1,93 a +2,50 |
| 3 (padrão) | 4,79 | −1,50 | −1,95 a +3,00 |

No `improviso_3` o mesmo rider ±3 dB custou **1,76 LU**; aqui custa 2,92. A
diferença é o material: aquele é um cover com andamento firme (BPM 136,00,
fronteiras em 5/5 escalas); este é improviso livre (autocorrelação do envelope
com r = 0,174) cuja dinâmica larga o rider lê como erro de volume.

**Não é bug, é parâmetro fora de faixa para este material** — e a decisão é de
ouvido. Variantes casadas em −14 LUFS em `work/ab_*.wav`, janela 117,4–132,4 s
do vídeo (atravessa a fronteira forte de 86,54 s do trecho):

| arquivo | o que é |
|---|---|
| `ab_0_seca.wav` | sem reverb, referência |
| `ab_1_conv_medio.wav` | **o que está no entregável** |
| `ab_2_conv_amplo.wav` | mais sala (wet −12,0, rt60 1,8) |
| `ab_3_freeverb.wav` | outro algoritmo |
| `ab_4_conv_rider0.wav` | reverb padrão, rider desligado — LRA 7,71 |
| `ab_5_conv_rider1.wav` | reverb padrão, rider ±1 dB — LRA 6,19 |

### Uma pendência que apareceu

O HPF de 70 Hz removeu **4,14% da energia** aqui, contra 1,07% no
`improviso_3`. O `violao_dsp.py` justifica o corte dizendo que "abaixo de 95 Hz
não há nota tocada" — o que foi medido *naquele* material. A nota mais grave do
violão é E2 = 82,4 Hz, acima do corte, então provavelmente é manuseio ou piso da
sala. **Não foi medido neste episódio.** Vale conferir antes de confiar.

## Plano de edição — medido, não executado

### 1. O plano é único e fixo, e é por isso que o vídeo parece parado

152,2 s de um só enquadramento. Não há segunda câmera e não há cobertura para
corte de plano — mas há **pixel sobrando**: o master é 3840x2160 e o entregável
é 1920x1080, ou seja **2,0x**.

E a câmera está parada. Deslocamento do fundo por correlação de fase, em
regiões estáticas, contra t = 40 s:

| t | dx | dy |
|---|---|---|
| 60 s | −2 px | −1 px |
| 90 s | −1 | 0 |
| 120 s | −1 | 0 |
| 150 s | 0 | +1 |
| 185 s | −2 | 0 |

Máximo de 2 px em 1080p ao longo de 145 s, e **sem tendência monotônica** — vai
e volta. É flutuação, não deriva, o mesmo critério que o
`docs/03-sincronismo-multipista.md` usa para dizer que um offset fixo segura.
Logo: **crop digital não precisa de estabilização.**

Isso permite três "câmeras" sintéticas, todas em **redução** — em nenhum
instante se amplia, que é a mesma honestidade que o `vertical.sh` exige do
`improviso_4`:

Quatro câmeras, renderizadas e olhadas na tela em t = 60 s e t = 120 s:

| câmera | crop no master | fator | papel |
|---|---|---|---|
| PG | 3840x2160 (inteiro) | 2,00x ↓ | estabelecer: abertura e fecho |
| **PM** | 2880x1620 em (460, 340) | 1,50x ↓ | **o plano base** |
| retrato | 2400x1350 em (900, 500) | 1,25x ↓ | rosto, mão esquerda e o braço na diagonal |
| close braço | 1920x1080 em (940, 660) | **1,00x** | o mais fechado: escala e mão esquerda |

1920x1080 é o limite exato: abaixo disso amplia.

**O PM devia ser o plano base do episódio, não o PG.** Visto na tela nos dois
instantes: ele tira a cama e a parede azul do canto direito, dobra o tamanho do
rosto e mantém a cabeça do violão. O PG passa a ter o papel que os planos
gerais têm — estabelecer o espaço — em vez de carregar 152 s sozinho. É a
mudança de maior efeito e menor custo do episódio inteiro, e não custa um pixel
de qualidade: ainda é redução de 1,5x.

**Close só no rosto não funciona, e foi preciso ver para saber.** Testadas
quatro janelas em t = 120 s: as duas mais apertadas (1920x1080 em (1000, 160) e
em (1450, 250)) deixam o rosto solto na metade direita com janela estourada
ocupando o resto do quadro, e o rosto está sempre voltado para baixo, para o
braço. O que funciona é abrir até **2400x1350 em (900, 500)**, onde entram a mão
esquerda e o corpo do violão e o braço cruza o quadro na diagonal. O retrato de
quem toca precisa do instrumento dentro.

Coordenadas medidas no frame de t = 60 s (master 3840x2160): rosto centrado em
~(1960, 630), cachos de x 1660–2270 e y 400–900; mão esquerda em (2050–2300,
1300–1470); cabeça do violão em (640–1300, 690–1080); corpo do violão em
(2100–3300, 1250–2160).

**Close na mão direita não cabe.** Ela fica em (3120–3400, 1880–2100), a ~440 px
da borda direita e ~60 px da inferior — um crop centrado nela sai do quadro, e
apertar mais amplia. É lição de enquadramento para a próxima gravação, não algo
a resolver na edição: **não deixar a mão de dedilhado na borda.**

### 2. Onde cortar: as fronteiras já estão medidas

`work/ep00_violao.secoes.tsv`. BPM 117,45, compasso 4/4 = 2,043 s, 12 blocos de
8,3 a 17,9 s. Forma: `A A' B B' C C' B'' A'' B''' C'' B'''' A'''`.

Corte de plano que cai no tempo lê como intencional. As fronteiras com desvio
**0 ms** para o tempo mais próximo, já convertidas para tempo de vídeo (relativo
+ 37,41 s):

| tempo do vídeo | bloco que abre | fronteira |
|---|---|---|
| **69,5 s** | B (A menor, confiável) | fraca, 5/5 escalas |
| **106,0 s** | C' | fraca, 4/5 |
| **142,9 s** | B''' | fraca, 5/5 |
| **165,2 s** | B'''' | **FORTE**, 3/5 |
| **179,6 s** | A''' (E maior, confiável) | **a mais forte do trecho**, 5/5, altura 1,00 |

E as FORTES (croma e MFCC concordam dentro de um compasso), com o desvio ao
tempo entre parênteses: 52,2 s (975 ms), 81,5 s (534 ms), 94,9 s (998 ms),
154,1 s (975 ms), 165,2 s (0 ms).

**A fase do tempo forte não é confiável aqui** — os dois estimadores discordam
em 511 ms, um tempo inteiro. O número que vale é o desvio ao TEMPO, não ao
tempo forte.

### 3. O improviso tem forma, e ela é o conteúdo do episódio

Quatro blocos com centro tonal **confiável** (separação ≥ 0,15 para o segundo
candidato de outra tônica):

| bloco | tempo do vídeo | centro | r | sep |
|---|---|---|---|---|
| B0 | 37,4 – 52,2 s | **E menor** | 0,772 | 0,386 |
| B2 | 69,5 – 81,5 s | **A menor** | 0,609 | 0,194 |
| B9 | 154,1 – 165,2 s | **D maior** | 0,688 | 0,188 |
| B11 | 179,6 – 189,6 s | **E maior** | 0,734 | 0,320 |

E o fecho é a retomada da abertura: B11 casa com B0 a **cosseno 0,971** (2º
melhor 0,685, separação 0,286 — "claro"), e o casamento de sequência aponta
0,743 para 1,02 s do trecho, também "claro". O `sobe` de B11 é **E +22,1 pontos
percentuais**, o maior evento de classe de altura do trecho.

Leitura: em E menor, **Am é iv e D é ♭VII**, e o improviso **fecha na tônica
maior**. Isso é vocabulário de harmonia funcional puro, e o episódio de
apresentação do canal já traz o assunto do canal dentro dele.

**Isso é hipótese, não resultado.** O Krumhansl-Kessler dá o centro tonal, não a
função, e E maior e E menor compartilham E e B. Precisa da confirmação do autor
— exatamente como o "bloco ambíguo" do `docs/05`. Se confirmar, é a camada de
legenda de harmonia do ep00 e ela sai de graça, dos números que já estão no TSV.

### 4. Contraluz severo, e ele explica um problema já registrado

Luma média por região, no master, em três instantes (0–255):

| região | t=45 s | t=90 s | t=150 s | p95 | estourado (≥250) |
|---|---|---|---|---|---|
| rosto | 50,6 | 69,0 | 81,8 | 172–249 | 0,1 – 4,3% |
| **janela** | 219,0 | 221,5 | 219,5 | 254–255 | **37,5 – 53,0%** |
| violão | 56,2 | 50,4 | 53,8 | 99–109 | 0,2 – 0,7% |
| parede | 74,6 | 81,5 | 86,9 | 101–111 | 0,1 – 1,1% |

O sujeito — rosto e violão — vive entre Y 50 e 82, ou seja 20 a 32% de luma. O
fundo da janela está em 219 com **até metade dos pixels clipados**.

Duas consequências práticas. Primeira: levantar as sombras não é estética, é
correção, e **não há highlight a perder** — a janela já está irrecuperável, então
comprimir os altos não custa informação que exista. Segunda: é essa janela que
produz os **7,6% de pixels de legenda abaixo de 4,5:1** que o `CLAUDE.md`
registra para o ep00, com o pior caso "branco sobre parede branca estourada".
São o mesmo fenômeno visto por dois instrumentos.

O ganho de sombra levanta ruído junto, e isso **não foi medido**. Medir antes de
entrar na cadeia.

### 5. Os 36 s de fala são o problema de retenção

A fala é meta-fala de teste: "tô fazendo um teste de gravação", "não sei qual que
é o ângulo", "essa imagem aqui não deve ficar boa". E é filmada com o celular na
mão, em selfie — os frames de 0 e 15,8 s são os piores do arquivo. A partir de
~31,6 s o celular está apoiado e o plano é o bom.

Ou seja, os primeiros 30 s concentram **a pior imagem e o menor interesse**,
antes de qualquer nota tocada. Os 9 cues do `.srt` estão em `out/ep00/ep00.srt`;
os úteis são o 1 ("Fala, galera do YouTube, brincadeira") e o 8 ("Só pra vocês
verem tocando"). Os cues 4 a 7 são hesitação e meta-fala.

Decidido em 05/09/2026: **cold open com fala enxuta.** A estrutura está montada
em `out/ep00/ep00_estrutura.v1.mp4` (168,800 s contra 168,789 s da soma dos
trechos — 11 ms de arredondamento de frame, o mesmo comportamento já registrado
para o `corta.sh`), aguardando avaliação na tela:

| # | fonte | dur | o que é |
|---|---|---|---|
| 1 | 179,563 → 189,616 | 10,053 s | o fecho em E maior, trazido para a frente |
| 2 | 1,700 → 3,820 | 2,120 s | "Fala, galera do YouTube, brincadeira." |
| 3 | 31,050 → 34,950 | 3,900 s | "Só pra vocês verem tocando… né?" |
| 4 | 36,900 → 189,616 | 152,716 s | "Show!" e o improviso inteiro |

Lista em `work/cortes_ep00_estrutura.txt`. Três coisas que a sustentam:

- **o corte de entrada do cold open cai numa fronteira medida** — a mais forte
  do trecho, 5/5 escalas, desvio 0 ms ao tempo — então a música já vira ali;
- **o fecho reaparece no fim, e isso é a favor.** Ele é a retomada da abertura
  (cosseno 0,971), então quem assiste reencontra o trecho como resolução em vez
  de como repetição;
- **o "Show!" virou a deixa da música.** O corte em 36,900 tira 1,95 s de pausa
  entre o "né?" e ele.

Saem os cues 2 a 7 — "não sei qual que é o ângulo", "essa imagem aqui não deve
ficar boa" e o resto da meta-fala —, e com eles quase toda a parte filmada com o
celular na mão.

**Esta versão tem duas gerações de AAC**, porque o `corta.sh` reencoda o áudio
do `_audio.mp4`. Para avaliar estrutura não importa. No entregável final, o
corte e o multiplano devem sair na mesma passada, com o áudio vindo do WAV — é
a divisão em duas frentes que o `docs/05` registra.

## Arquivos

| caminho | o que é |
|---|---|
| `out/ep00/ep00_audio.mp4` | **o entregável de áudio** |
| `out/ep00/ep00_audio.v1.mp4` | a versão de 24/08, referência do `CLAUDE.md` |
| `out/ep00/ep00_norm.mp4` | vídeo pronto, áudio bit-idêntico ao master |
| `work/ep00_violao.wav` | violão tratado, 152,256 s |
| `work/ab_*.wav` | 6 variantes casadas em −14 LUFS |
| `work/ep00_violao.secoes.tsv` | as 12 fronteiras, centros tonais, repetição |
| `work/ep00_violao.secoes.png` | croma, auto-similaridade, novidade, trajetória |
| `out/ep00/ep00_estrutura.v1.mp4` | o cold open montado, para avaliar na tela |
| `work/cortes_ep00_estrutura.txt` | a lista de trechos, na ordem de saída |
| `work/ep00.mp4` | symlink para o master, só para o nome do projeto |
