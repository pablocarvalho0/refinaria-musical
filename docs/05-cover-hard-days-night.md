# Cover instrumental — improviso_3, 41 s em diante

Estado em 05/09/2026, 01:49. Frente aberta: legenda de harmonia.

## Onde parou

O entregável está pronto e aprovado:

```
out/improviso_3/improviso_3_cover_final.mp4
```

1080x1920, 60 fps CFR, 3642 frames, 60,700 s, SAR 1:1, AAC 48 kHz `language=por`.
Medido no arquivo final: **−14,0 LUFS integrado, true peak −0,9 dBFS**.

Ele é o recorte de `improviso_3` a partir de 41,000 s — onde a fala já acabou
(a região MÚSICA começa em 24,2 s) e começa o cover instrumental — com áudio
tratado, cartela de abertura, cartela de créditos e fade-out.

## Como reproduzir cada peça

```bash
cd ~/video && source .venv/bin/activate

# 1. o corte
./scripts/corta.sh out/improviso_3/improviso_3_audio.mp4 \
    work/cortes_improviso_3_cover.txt      # -> _audio_final, renomeado para _cover

# 2. o áudio tratado (WAV, 60,700 s exatos)
./scripts/violao.sh out/improviso_3/improviso_3_norm.mp4 \
    --inicio 41.000 --duracao 60.700 \
    --saida work/improviso_3_cover_audio.wav --ab --ab-janela 30.0:45.0

# 3. as cartelas (vídeo com -c:a copy, áudio intocado)
./scripts/monta-cartelas.sh ...   # ver o cabeçalho do script

# 4. a junção — uma geração de AAC só, vídeo sem reencode
ffmpeg_lim -y -i work/improviso_3_cover_video.mp4 \
    -i work/improviso_3_cover_audio.wav \
    -map 0:v -map 1:a -c:v copy \
    -af "afade=t=out:st=59.2:d=1.5,apad" \
    -c:a aac -b:a 192k -ar 48000 -metadata:s:a:0 language=por \
    -movflags +faststart -shortest \
    out/improviso_3/improviso_3_cover_final.mp4

# 5. a análise de seções
python scripts/secoes.py out/improviso_3/improviso_3_norm.mp4 \
    --inicio 41.0 --dur 60.7 --destino work/improviso_3_cover
```

A divisão em duas frentes (WAV de um lado, vídeo com `-c:a copy` do outro) existe
para o AAC ser gerado **uma vez**. Não montar áudio e cartela no mesmo passo.

## O que decidir amanhã

**1. O que foi tocado entre 27,0 e 34,1 s.** É a pergunta que destrava tudo — ver
"O bloco ambíguo" abaixo.

**2. Qual reverb fica.** Em `work/`: `ab_0_seca.wav` (referência sem reverb),
`ab_1_conv_medio.wav` (o que está no vídeo), `ab_2_conv_amplo.wav` (mais sala),
`ab_3_freeverb_medio.wav` (outro algoritmo). As quatro estão **casadas em
−14 LUFS de propósito**, senão a mais alta ganharia sozinha no teste de ouvido.

**3. O handle da cartela de créditos.** Sai `@PabloCarvalho-q1o`, vindo de
`[marca] handle`. Tem cara de handle autogerado do YouTube. Trocar nos tokens e
regerar, ou tirar o handle da cartela.

**4. Levar dois achados para o `CLAUDE.md`** — não feito hoje porque o arquivo
estava com 223 linhas modificadas por outra sessão.

## A legenda de harmonia — o plano

Duas camadas, ambas saindo de `marca/tokens.toml`:

**Camada de seção**, trocando nas seis fronteiras medidas: rótulo do bloco em
cima, progressão com as funções embaixo. No refrão, `G · C9 · G · F` sobre
`I · IV · I · ♭VII`. Na ponte, `Bm · Em · Bm · G · Em · C · D` sobre
`iii · vi · iii · I · vi · IV · V`.

**Camada de destaque**, nos instantes medidos de F natural (28,24 s, 38,82 s,
51,18 s): realce curto marcando `♭VII · empréstimo modal`.

Nada de acorde a acorde. Alinhamento por acorde exigiria reconhecimento
automático, que este projeto já descartou com número (`autochord`, 25 classes a
~67%, sem sétimas). Seção medida + progressão da cifra + o ♭VII no instante
exato: tudo isso é verdadeiro, e a precisão que não temos não é fingida.

**A letra não entra.** Obra protegida; queimá-la na tela distribui o texto. A
legenda de harmonia foi escolhida no lugar, e é melhor para o canal.

### Progressão de referência

Do CifraClub, centro **G maior** (a página declara "Tom: C" num campo, mas os
acordes não deixam dúvida):

| seção | acordes | funções |
|---|---|---|
| refrão | `G – C9 – G – F` … `G – C – D – G – C9 – G` | I – IV – I – ♭VII … IV – V – I |
| ponte | `Bm – Em – Bm – G – Em – C – D` | iii – vi – iii – I – vi – IV – V |

**O F é ♭VII, empréstimo do mixolídio — não modulação.** Vale confirmar contra o
que foi realmente tocado.

## A medição de seções

`work/improviso_3_cover.secoes.tsv` e `.secoes.png`.

**Referencial: 0,000 = 41,000 s de `improviso_3_norm.mp4`.**

Firme: **BPM 136,00**, compasso 1,765 s, e as **seis fronteiras aparecem em 5 de
5 escalas de kernel** (variação de 2,7× no tamanho), todas caindo em cima de um
tempo rastreado com desvio de 0,0 ms.

| bloco | início | fim | dur | centro tonal | fronteira |
|---|---|---|---|---|---|
| B0 | 0,000 | 9,660 | 9,66 s | D maior, inconclusivo | borda |
| B1 | 9,660 | 18,901 | 9,24 s | G maior, fraco | fraca (só croma) |
| B2 | 18,901 | 26,982 | 8,08 s | **B menor, r 0,884, confiável** | **forte** |
| B3 | 26,982 | 34,133 | 7,15 s | A menor, inconclusivo | fraca (só croma) |
| B4 | 34,133 | 44,861 | 10,73 s | G maior, inconclusivo | **forte** |
| B5 | 44,861 | 53,545 | 8,68 s | G maior, inconclusivo | média |
| B6 | 53,545 | 60,695 | 7,15 s | G menor, fraco | média |

Sete blocos medidos, sete blocos descritos pelo autor. A ponte está isolada e é
o **único bloco com centro tonal confiável**; as classes de altura que a
distinguem são B +8,6 pp, F♯ +4,1 e E +1,0 — o Bm e o Em. Ela volta uma vez, em
51,18 s, com 71% da força.

### O bloco ambíguo

**B3 (26,982–34,133 s) não se agrupa nem com refrão nem com ponte**, tem centro
tonal inconclusivo e carrega o maior evento de F natural do trecho (28,24 s,
F +9,6 pp com F♯ −1,9 pp). Duas leituras que a medição **não separa**:

- **cauda da ponte** — saindo do Bm e passando pelo F antes de voltar ao refrão;
  a ponte seria de 18,9 a 34,1 s;
- **refrão já com o ♭VII** por cima; a ponte termina mesmo em 27 s.

Se for a primeira, e dado o cheiro de A menor, pode ter havido **modulação de
verdade** — o que muda o rótulo na tela. Resolver com o autor.

### O que ficou inconclusivo

Qual bloco repete qual (perfil médio de croma e casamento de sequência empatam),
o período do ciclo (27,4–28,2 s pelas âncoras tonais, 26,0–26,6 pelas fronteiras,
35,5 pelo melhor casamento) e a fase do tempo forte (dois estimadores discordam
em 441 ms). O MFCC não é testemunha útil aqui: violão solo tem timbre quase
constante, então a curva fica abaixo do piso e só dispara no acorde final.

## O que este trabalho ensinou e vale para os outros episódios

> **Atualização de 11/09/2026.** O candidato desta seção virou decisão: o
> `afftdn` saiu da cadeia de FALA do `audio.sh` em 06/09/2026, medido em
> episódio com fala, que era a metade que faltava. A transcrição melhora sem
> ele (ep00 88,2% → 93,3%; gravação externa 74,7% → 91,1%), e a compensação de
> latência de 25 ms saiu junto. A medição abaixo continua valendo como o
> registro de **por que** ele saiu — e a tabela diz "atual" no estado de 05/09.

**O denoise do `audio.sh` está raspando sinal, e agora tem número.** Neste
material **não existe piso de ruído**: acima de 120 Hz as janelas quietas ficam
37 a 58 dB abaixo do espectro médio. O `afftdn=nr=10:nf=-30` come
**2,60 ± 0,29 dB** de energia acima de 4 kHz nos ataques, que num dedilhado é a
unha, e remove 0,135% do sinal. Confirma por medição a suspeita já registrada
sobre as consoantes. Candidato claro: trocar `afftdn` por high-pass — medir antes
num episódio com fala, porque isto foi medido em violão solo.

| ajuste | Δ agudo nos ataques | Δ profundidade |
|---|---|---|
| `afftdn=nr=10:nf=-30` (atual) | **−2,60 ± 0,29 dB** | +0,63 |
| `nr=6:nf=-40` | −0,68 ± 0,13 | +0,36 |
| `nr=3:nf=-50` | −0,07 ± 0,05 | +0,08 |
| `anlmdn` | +0,71 | (atrasa 7,91 ms) |

**Compressor achata o dedilhado; ganho lento não.** Mesmo nivelamento, custo
diferente:

| | Δ espalhamento ST | Δ profundidade | Δ ataque |
|---|---|---|---|
| rider ±3 dB | −1,76 LU | **+0,20 dB** | 0,00 ms |
| `acompressor −18 dB 3:1` | −1,63 LU | **−7,66 dB** | −4,96 ms |

**Toda cartela sobre imagem precisa de scrim, e isso é medição, não estética.**
Neste material **não existe faixa horizontal onde branco puro alcance 4,5:1** —
p95 de luminância de 0,33 a 0,84 nas doze bandas, o que dá 1,2:1 a 2,7:1 em
qualquer lugar. Sem scrim o texto dos créditos mede **1,0:1**, branco sobre
branco. Com `scrim_forca = 0,72`: abertura 9,3–10,6:1, créditos 6,5:1, 0,0% de
pixel abaixo do limiar no arquivo já encodado. É o mesmo princípio que o
`CLAUDE.md` registra para a capa: o que falta é escurecer o fundo.

**Âncore pela caixa de tinta, não pela soma das alturas de linha.** A primeira
versão da cartela terminava 4 px dentro da safe area — o descendente do `y` mais
o contorno, que altura de linha nenhuma prevê. Quatro pixels somem atrás dos
botões do Reels sem nada acusar. A correção é desenhar, medir com `getbbox` e só
então posicionar.

**Mediana solta de transiente mente.** A primeira comparação de reverb acusou a
convolução atrasando o ataque em +2,83 ms — mas o erro-padrão daquela mediana era
1,94 ms. Refeito **pareado nota a nota**, as nove configurações ficaram entre
+0,00 e +0,04 ms. A diferença não existia. Medir transiente pareado, sempre.

## Arquivos

| caminho | o que é |
|---|---|
| `out/improviso_3/improviso_3_cover_final.mp4` | **o entregável** |
| `out/improviso_3/improviso_3_cover.mp4` | corte cru, antes de áudio e cartelas |
| `work/improviso_3_cover_audio.wav` | áudio tratado, 60,700 s exatos |
| `work/ab_*.wav` | as quatro variantes de reverb, casadas em −14 LUFS |
| `work/improviso_3_cover_video.mp4` | vídeo com cartelas, áudio intocado |
| `work/improviso_3_cover.abertura.png` | cartela de abertura, RGBA |
| `work/improviso_3_cover.creditos.png` | cartela de créditos, RGBA |
| `work/improviso_3_cover_video.preview-*.png` | frames do render, para conferir |
| `work/improviso_3_cover.secoes.tsv` | as fronteiras medidas |
| `work/improviso_3_cover.secoes.png` | croma, auto-similaridade, novidade, trajetória tonal |
| `work/cortes_improviso_3_cover.txt` | a lista do corte |
| `scripts/violao.sh`, `scripts/violao_dsp.py` | tratamento de áudio |
| `scripts/cartelas_improviso.py`, `scripts/monta-cartelas.sh` | as cartelas |
| `scripts/valida-cartela.py` | contraste WCAG da cartela contra o vídeo real |
| `scripts/secoes.py` | análise de seções |

Dependências novas no venv: `pedalboard 0.9.24`, `soundfile 0.14.0`,
`scipy 1.18.1`, `librosa 1.0.0`, `matplotlib 3.11.1`, `numba 0.67.0`,
`scikit-learn 1.9.0`, `soxr 1.1.0`.
