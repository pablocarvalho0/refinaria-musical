# Câmera virtual sobre plano fixo — medido em 05/09/2026

Estado: **três variantes geradas, aguardando a validação do Pablo na tela.**
A mecânica está medida; o ritmo, não. Ver "O que falta".

## O problema

O `improviso_3` é um plano fixo: celular no tripé, 60 s, nada se move. O
material é bom e o enquadramento é único — e é isso que faz a peça estacionar
na tela por volta dos 20 s. A observação é do Pablo, assistindo, antes de
haver número.

## A margem existe, e é exatamente 2x

O master é 3840x2160 com `rotation=-90`, ou seja, **exibido 2160x3840**. O
entregável é 1080x1920. As proporções são idênticas (0,5625) e sobra um fator
2 inteiro.

Isso decide o teto: **zoom 2,00 é recorte 1:1**, cada pixel da saída vindo de
um pixel do master. Até lá é redução. Acima é ampliação, e o `camera.py`
recusa com o número na mensagem. É o mesmo critério que autorizou o
empilhamento do `improviso_4` — o que sustenta o corte é a resolução da
fonte, não o gosto de quem enquadra.

## `scale` tem `eval=frame` — o `zoom-cmds.py` supôs que não

O `zoom-cmds.py` (30/08) documenta por que `crop` e `zoompan` não servem para
animar um zoom, e as duas razões continuam válidas:

| | por que não |
|---|---|
| `crop` | reavalia só `x` e `y` por frame; `w`/`h` são resolvidos na configuração |
| `zoompan` | só aproxima (`z` tem piso em 1) e anda em passo inteiro |

A terceira linha é que estava errada. Ele conclui que `scale` só é alcançável
por `sendcmd`, e por isso gera um arquivo com um comando por frame do master.
Mas **este ffmpeg 6.1.1 tem `eval=frame` no `scale`**:

```
eval  <int>  ..FV.......  specify when to evaluate expressions
  init   0    eval expressions once during initialization
  frame  1    eval expressions during initialization and per-frame
```

Com isso a animação inteira cabe em duas expressões de `t` — sem arquivo de
comandos intermediário e sem a possibilidade de um comando se perder.
Verificado renderizando 3 s: 180 frames, 1080x1920 exatos.

**O `zoom-cmds.py` não foi mexido.** Ele serve o `vertical.sh`, que está
montado e aprovado; trocar a mecânica de uma peça pronta para ganhar elegância
é risco sem retorno. Fica registrado aqui para quando o `vertical.sh` for
mexido por outro motivo.

## `in_w` no crop NÃO acompanha um scale com `eval=frame`

**É a armadilha central deste script, e ela é silenciosa.** O `vertical.sh`
recentra lendo `overlay_w` — "o recentramento se prende à escala, não ao
relógio" — e a primeira versão daqui repetiu o padrão com `in_w`:

```
scale=w='2*ceil(1080*Z(t)/2)':h=-2:eval=frame
crop=1080:1920:'max(0,min(in_w-1080, X(t)*in_w/2160-540))':'...'
```

`in_w` e `in_h` são resolvidos na **configuração do link** e ficam parados.
Com o primeiro enquadramento em zoom 1,00, o crop leu 1080 pelos 60 s
inteiros, e todo enquadramento ampliado saiu deslocado para o canto superior
esquerdo. Código de saída 0, nenhum aviso, o vídeo se move — só se move para
o lugar errado.

Diagnóstico confirmado por reprodução: se `in_w` estivesse travado em 1080, o
frame de t=12 s equivaleria a um `crop=1080:1920:160:180` sobre a imagem
2160x3840. Renderizado à mão, esse crop devolve **o mesmo enquadramento** que
saiu do vídeo defeituoso.

**O preview em frame estático não pega o defeito** — ali o `scale` é fixo e
`in_w` está certo. Foram quatro enquadramentos validados na tela, todos
corretos, e o vídeo saiu errado mesmo assim. A lição é a que o `processa.sh`
já tinha ensinado com o `scale=1920:1080`: o que engana não é o valor errado,
é o caminho que só passa a existir em movimento.

A correção é o crop **repetir** a expressão de largura em vez de perguntá-la:

```
W(t) = 2*ceil(1080*Z(t)/2)      H(t) = 2*ceil(1920*Z(t)/2)
scale=w='W(t)':h='H(t)':eval=frame
crop=1080:1920:'max(0,min(W(t)-1080, X(t)*W(t)/2160-540))':'...'
```

Continua preso à escala e não ao relógio — é a mesma função de `t`, avaliada
no mesmo frame —, só que por construção em vez de por leitura.

A altura passou a ser explícita pelo mesmo motivo: com `h=-2` quem escolhe é
o swscaler, e o clamp precisa do número exato — pedir ao crop um `y` dois
pixels além do que ele escolheu mata o render. O preço é a largura e a altura
arredondarem para par cada uma por sua conta. **Anisotropia máxima medida
varrendo z de 1,00 a 2,00: 1,00169 (0,169%)**, contra os 3,16x que o
`processa.sh` corrigia em 05/09. Um rosto de 700 px sai 1,3 px mais largo.

`ceil` e não `floor` porque um `floor` devolvia 1078 num zoom de 0,999, e o
crop de 1080 morre sem imagem.

Fora das bordas o crop é preso com `max`/`min`. O close de reação pede o rosto
centrado em y=850, e a janela de 1920 encostaria a −110: ela para em 0. O
relatório do `camera.py` imprime `x-preso`/`y-preso` quando isso acontece,
porque o enquadramento entregue passa a ser outro — e outro que só o preview
mostra.

## O sincronismo com o áudio já tratado, medido

O risco real deste caminho não é a imagem: é o vídeo vir do **master** enquanto
o áudio aprovado (`work/improviso_3_cover_audio.wav`) veio do `_norm`, com um
`-r 60` a mais no meio. Se houvesse deriva, o ataque da mão sairia de hora com
o som — e no fim do trecho, onde ninguém procura.

Medido com câmera fixa em z=1,00 sobre os 3 s finais do trecho (86,0 s do
master contra 45,0 s do entregável aprovado), varrendo o deslocamento:

| deslocamento | −3 | −2 | −1 | **0** | +1 | +2 | +3 |
|---|---|---|---|---|---|---|---|
| PSNR y (dB) | 27,69 | 28,95 | 30,94 | **34,04** | 32,37 | 29,98 | 28,41 |

Pico limpo em zero, com 3,1 dB de queda a um frame. **Não há deriva**: o vídeo
tirado do master casa frame a frame com o entregável aprovado, logo casa com o
WAV. Os 34 dB de teto são a diferença de gerações de x264, não desalinhamento.

**A varredura é o método, não o valor absoluto.** Uma medição direta em outro
trecho deu 21,5 dB e não queria dizer nada: a folhagem da árvore é alta
frequência, um zoom de 0,1% já a desloca um pixel, e o PSNR desaba sem que
nada esteja errado. Quem responde a pergunta é a **forma da curva** — pico em
zero e simétrica —, não a altura dela.

## O que o material tem, e o que ele não tem

Sondados oito instantes do trecho (43, 50, 57, 64, 71, 79, 86 e 95 s do
master), em coordenadas do quadro já girado:

**Não existe plano da mão esquerda.** Ela está **cortada pela borda esquerda
em todos os oito**. O que entra no quadro é o dorso e o polegar, centrados em
torno de x≈100; os dedos que pisam as cordas ficam fora. Um close ali entrega
uma mão truncada. Não é limitação de zoom — é o que foi gravado.

Se a mão esquerda importar, ela é **decisão de gravação**: afastar o tripé um
palmo à esquerda, ou girar o corpo. Enquadramento não recupera pixel que não
foi registrado.

Os quatro enquadramentos que o material sustenta, validados em frame estático
antes de qualquer render:

| enquadramento | centro (x, y) | z | janela no master |
|---|---|---|---|
| geral | 1080, 1920 | 1,00 | 2160x3840 em (0,0) |
| médio (torso + violão) | 1150, 1500 | 1,45 | 1490x2648 em (405,176) |
| reação (rosto) | 1250, 960 | 2,00 | 1080x1920 em (710,0) |
| mão direita | 1400, 2280 | 2,00 | 1080x1920 em (860,1320) |

A mão direita fica inteira no quadro nos oito instantes, migrando de ~(1330,
2150) para ~(1570, 2240) ao longo do trecho. **O alvo fixo aguenta o drift**:
conferido em 50, 79 e 95 s, ela fica centrada nos três. Não foi preciso animar
o pan para segui-la.

O y=2280 saiu de uma correção na tela: com 2170 entrava um pedaço de queixo no
topo do quadro, e um pedaço de queixo lê como erro de enquadramento.

## O ritmo saiu das seções medidas, não do gosto

As três variantes usam as fronteiras que o `secoes.py` já tinha medido em
`work/improviso_3_cover.secoes.tsv` — BPM 136,00, compasso 1,765 s, seis
fronteiras estáveis em 5 de 5 escalas de kernel.

As duas trocas mais marcadas caem nas duas fronteiras classificadas **FORTE**
(18,901 e 34,133), onde croma e MFCC concordam dentro de um compasso. A de
18,901 é a mais confiável do episódio — B menor, r 0,884, separação 0,209 — e
é onde entra o close de reação: **a harmonia muda de centro e a câmera muda de
assunto no mesmo instante.**

| variante | movimentos | transição | o que testa |
|---|---|---|---|
| `v1-respiro` | 1 arco | 20–25 s | o mínimo: ninguém percebe o movimento, só deixa de perceber que está parado |
| `v2-secoes` | 5 trocas | 0,90 s | o meio, ancorado nas fronteiras |
| `v3-batida` | 11 cortes | seca | o extremo do Instagram: corte seco na grade de dois compassos |

**O movimento fica todo entre 7,0 s e 52,5 s**, que é a janela entre a saída
da cartela de abertura e a entrada dos créditos. Texto sobre imagem que desliza
incomoda, e as cartelas foram desenhadas para o enquadramento geral.

**O risco conhecido da v3**: como o plano é fixo, o corte seco muda só a
escala, não o ângulo. Pode ler como snap zoom ou como glitch de encode. É
exatamente o que o teste existe para decidir; se ficar duro, `0.18` na coluna
`trans` transforma todos em snap, sem tocar em código.

## Conferido nas três, depois da correção

Cada variante foi conferida em frame, nos instantes em que cada enquadramento
deveria estar **estabelecido** — não durante as transições, onde qualquer
coisa parece plausível:

| variante | instantes conferidos | resultado |
|---|---|---|
| `v1-respiro` | 5, 27, 50 s | geral, z=1,28 no ápice, voltando ao geral |
| `v2-secoes` | 5, 14, 22, 30, 40, 48, 55, 59 s | os seis enquadramentos, todos no lugar |
| `v3-batida` | 10, 14, 20, 28, 35, 42 s | mão, reação, mão, médio, reação, mão |

O áudio das três é o mesmo WAV aprovado, e mede igual ao entregável de
referência: **I −14,0 LUFS, LRA 2,3 LU, true peak −0,9 dBFS**. Geometria
idêntica também: 1080x1920, 60 fps CFR, 3642 frames, SAR 1:1, AAC 48 kHz
`language=por`. Uma geração de AAC, como manda o doc 05.

## Custo

3 m 12 s de render por variante (3642 frames, decode do 4K na GPU, `scale` por
frame e x264 `-crf 20 -preset fast` na CPU), mais ~1 min de cartelas e a
junção. O arquivo sai entre 85 e 94 MB contra os 64 MB do entregável parado:
zoom contínuo é movimento, e movimento custa bitrate. A `v2` é a mais pesada
das três — transição suave de 0,9 s gera mais residual que corte seco.

Nenhuma variante chegou perto do teto do `ffmpeg_lim`.

## Reproduzir

```bash
cd ~/video && source .venv/bin/activate

./scripts/dinamica.sh inbox/improviso_3.mp4 \
    out/improviso_3/testes-dinamica/v2-secoes.camera.tsv \
    work/improviso_3_din_v2-secoes_v.mp4 --inicio 41.0 --duracao 60.700

./scripts/monta-cartelas.sh work/improviso_3_din_v2-secoes_v.mp4 \
    work/improviso_3_din_v2-secoes_cart.mp4 \
    work/improviso_3_cover.abertura.png:0.60:7.00 \
    work/improviso_3_cover.creditos.png:52.50:fim

ffmpeg_lim -y -i work/improviso_3_din_v2-secoes_cart.mp4 \
    -i work/improviso_3_cover_audio.wav \
    -map 0:v -map 1:a -c:v copy \
    -af "afade=t=out:st=59.2:d=1.5,apad" \
    -c:a aac -b:a 192k -ar 48000 -metadata:s:a:0 language=por \
    -movflags +faststart -shortest \
    out/improviso_3/testes-dinamica/improviso_3_cover_v2-secoes.mp4
```

`SECO=1` no `dinamica.sh` imprime o filtro e o relatório de enquadramentos sem
renderizar nada — é por onde se confere uma receita nova antes de gastar
3 minutos.

Os `_v.mp4` das três ficaram em `work/`: são os caros de refazer, e é sobre
eles que se troca cartela sem repetir a câmera.

## O que falta

- [ ] **A validação na tela.** As três estão em
      `out/improviso_3/testes-dinamica/`. O ritmo é a única coisa aqui que
      não tem número, e não vai ter: quem decide é assistir.
- [ ] **O close de reação no fim está sob os créditos.** O melhor sorriso do
      episódio é por volta de 57 s do corte (98 s do master), quando ele baixa
      o violão — e a cartela de créditos entra em 52,5 s. Vale testar um close
      ali: o rosto ficaria acima do scrim. Não entrou nas três porque a
      primeira decisão é a linguagem, não o detalhe.
- [ ] **n=1.** Um episódio, um plano fixo, um enquadramento. Os quatro
      enquadramentos da tabela são deste material e não generalizam.
