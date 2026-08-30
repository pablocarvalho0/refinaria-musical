# Identidade visual — medida em 30/08/2026

> **Segunda rodada, 30/08/2026.** A primeira proposta era turquesa. Foi
> substituída por terracota/salmão, extraído do material escrito do próprio
> autor. O registro de por que está em "A direção mudou" no fim deste arquivo —
> vale a leitura antes de reabrir a discussão de cor.

Registro das escolhas de aparência do canal e de como cada número foi obtido.
Os valores vivem em `marca/tokens.toml`; este documento é o porquê.

## Por que tokens e não um manual

Um manual de marca é consultado duas vezes e esquecido. O que sobrevive a 47
episódios é o valor que o script aplica sozinho. Por isso a identidade entra
como **dado que o `legenda.py` lê**, e não como documento que alguém precisa
lembrar de seguir — é o princípio 3 do `CLAUDE.md` ("script escrito uma vez
roda para sempre") aplicado à aparência.

O documento existe só para registrar o julgamento, como o resto do projeto.

## A métrica da fonte, medida

Renderizando com o próprio libass, em seis tamanhos (40 a 72), sobre a linha
mais longa do `ep00` (`"é um teste, então posso fazer mais vídeos"`, 41
caracteres):

| tamanho | largura da linha | altura da caixa | px por caractere |
|---|---|---|---|
| 40 | 676 px | 33 px | 16,49 |
| 48 | 812 px | 39 px | 19,80 |
| 54 | 912 px | 44 px | 22,24 |
| 60 | 1014 px | 48 px | 24,73 |
| 66 | 1116 px | 53 px | 27,22 |
| 72 | 1216 px | 58 px | 29,66 |

A relação é exatamente linear — 0,4119 px de largura por caractere por ponto
de tamanho, idêntico nos seis. Daí:

    largura da linha = n_caracteres × 0,4119 × tamanho
    altura da caixa  = 0,8148 × tamanho

**É o que permite dimensionar um formato novo por cálculo em vez de tentativa
e erro.** Se a família da fonte mudar, remedir: os números são da Inter.

## Os dois formatos

O 16:9 já estava validado na tela e **não foi tocado** — o `.ass` gerado depois
da mudança é byte a byte igual ao de antes. O 9:16 é novo.

| | 16:9 | 9:16 |
|---|---|---|
| PlayRes | 1920x1080 | 1080x1920 |
| tamanho | 54 | 78 |
| contorno / sombra | 3,2 / 1,0 | 4,6 / 1,4 |
| margem lateral | 140 | 60 |
| margem inferior | 90 (8,3%) | 480 (25%) |
| caracteres por linha | 42 | 29 |
| linhas no máximo | 2 | 3 |

**O vertical não é o horizontal reescalado.** O critério de dimensionamento é
caracteres por linha, não porcentagem da tela: linha curta lê melhor em tela
pequena e em movimento. Com margem lateral 60 sobram 960 px, e a fonte 78 dá
29,9 caracteres por linha. Contorno e sombra mantêm a proporção do 16:9
(5,93% e 1,85% do tamanho), que é o que já foi aprovado a olho.

No 16:9 o limite de 42 caracteres nem é espacial: a área útil de 1640 px
comportaria 73, e a linha mais longa do `ep00` usa 56% dela. Ali o 42 é norma
de leitura, herdada da prática de legendagem.

## O que só apareceu medindo: as linhas saíam da tela

O `.ass` usa `WrapStyle: 2`, que **desliga a quebra automática do libass**: a
linha que sai do Python é a que vai para a tela, inteira. E o `quebra_linhas`
usava `MAX_CHARS_LINHA = 42` como se fosse universal.

Aplicando os 42 do horizontal ao vertical, na fonte 78:

| | linhas | mais longa | estouram a margem |
|---|---|---|---|
| `ep00` no 9:16 | 16 | 41 caracteres = 1318 px | **10 de 16** |
| `improviso_2` no 9:16 | 32 | 43 caracteres = 1382 px | **17 de 32** |

A pior linha ficava 646 px fora da tela — mais de meia largura de texto que
simplesmente não existiria para quem assistisse, sem erro nenhum no console.

A correção separa dois conceitos que estavam no mesmo número:

- **o teto de 84 caracteres por cue é norma de leitura** e define os tempos.
  Fica no `legenda.py`, igual nos dois formatos, porque texto e tempo não
  podem mudar entre o longo e o corte vertical tirado dele;
- **onde a linha quebra é apresentação** e depende da largura. Foi para os
  tokens (`chars_por_linha`, `linhas_max`).

Depois disso: nenhuma linha estoura em nenhum dos dois formatos, e a mais
longa do vertical usa 900 px dos 960 disponíveis.

**A promessa que sobrevive é exatamente esta**, e vale enunciá-la com precisão
porque é o que torna o corte vertical barato: os dois formatos têm os **mesmos
cues, os mesmos tempos e o mesmo texto**; o que muda é só onde a linha quebra.
No `ep00` são 9 cues nos dois, com 16 linhas no horizontal e 20 no vertical.

Conferir por `diff` da linha inteira do `Dialogue` acusa diferença — e deve
acusar, porque a string carrega os `\N`. A verificação certa compara tempos e
texto com as quebras removidas.

## Legibilidade sobre o vídeo real, medida

`scripts/valida-legenda.py` renderiza cada cue com e sem a legenda queimada,
usa os pixels que mudaram como máscara do texto e mede contraste WCAG. No
`ep00`, oito cues amostrados:

| | pior contraste sem contorno | pixels abaixo de 4,5:1 | com contorno |
|---|---|---|---|
| 16:9 | 1,2:1 | 7,6% | 11,5:1 |
| 9:16 | 1,6:1 | 12,0% | 11,5:1 |

**É o contorno que torna a legenda independente do fundo.** Sem ele, 7,6% do
texto no horizontal e 12,0% no vertical ficariam abaixo do limiar de
legibilidade AA — e o pior caso, 1,2:1, é texto branco sobre parede branca
estourada, ou seja, invisível. Com o contorno o pior caso é 11,5:1 em todo
lugar, porque o texto passa a ser julgado contra o próprio contorno e não
contra a cena.

O vertical sofre mais (12,0% contra 7,6%) porque o corte central pega mais
parede clara e a fonte maior cobre mais área.

Isso também dá o critério para mexer no contorno depois: se alguém quiser
afiná-lo por estética, o número a vigiar é a última coluna, não o gosto.

## O que NÃO foi medido: a safe area

`margem_inferior = 480` (25% da altura) é a única peça desta identidade
apoiada em fonte secundária: vem da documentação do `browser-use/video-use`,
que usa 31% alegando que a interface de Reels e Shorts cobre os 25–30%
inferiores. **Não foi verificada no aplicativo.**

E é justamente a que decide se a legenda fica atrás dos botões.

Para medir de verdade existe `scripts/gabarito-safe-area.sh`, que gera uma
régua de 8 segundos rotulada em porcentagem e em pixels, com 25% em amarelo e
30% em laranja, mais uma linha de exemplo na posição real da legenda. O
procedimento: publicar como rascunho no Reels e no Shorts, tirar print dos
dois, ver até onde a interface cobre, e escrever o valor medido nos tokens.

Enquanto isso não for feito, os 25% são a melhor estimativa disponível, não um
fato — e está assim marcado no `tokens.toml`.

## Uma armadilha de ffmpeg que custou duas tentativas

Duas, na verdade, e as duas silenciosas:

**`-ss` antes de `-i` rebaseia os timestamps para zero**, então o filtro `ass`
procura a legenda na hora errada e o frame sai limpo. A primeira validação
inteira mediu contraste de fundo contra fundo sem acusar nada. Precisa de
`-copyts`, e o `valida-legenda.py` já usa.

**`%` solto no `drawtext` descarta o rótulo inteiro** com um mero warning
`Stray %`. A primeira versão do gabarito saiu com todas as réguas sem legenda.
O texto precisa chegar ao filtro como `\%`, depois de o bash e o parser do
filtergraph comerem uma barra cada um.

## A direção mudou — e o argumento antigo não sobreviveu

A primeira proposta era um acento turquesa, defendida assim: o material filmado
é 96% quente (67% vermelho, 15% laranja, 14% magenta em 633.600 pixels), então
um acento quente se dissolveria na imagem e um frio saltaria.

A medição continua válida. **A conclusão não.**

A medição de contraste feita depois, na mesma sessão, estabeleceu que **o
acento nunca vai sobre a foto**: sobre imagem só o branco tem contraste
garantido, e o acento vive em chip, barra e fundo sólido. A competição com o
material, que era toda a justificativa para o frio, não acontece na prática. O
argumento estava tecnicamente correto e resolvia um problema que a própria
regra seguinte eliminou.

Do outro lado havia uma razão que não foi considerada: já existia material
escrito com direção estabelecida — `~/Documents/proj-harmonia`, agosto de 2026 —
e harmonia funcional é assunto de livro e de tradição. Uma identidade que
conversa com esse material vale mais que uma que contrasta com os frames.

E o critério que decide: **o autor não se reconheceu no turquesa.** Identidade
que o autor não veste não funciona, por melhor que seja a defesa.

### A paleta nova foi medida, não escolhida

Renderizando `guia-harmonia-funcional.pdf` e `plano-playlist-harmonia.pdf` e
isolando os pixels saturados (0,21% do total), sobram duas cores:

| cor | matiz | luminância | onde funciona |
|---|---|---|---|
| terracota `#AE4E2A` | 16° | 0,146 | texto sobre claro (5,0:1), fundo de chip (4,8:1) |
| salmão `#DEA87E` | 26° | 0,450 | acento sobre escuro (8,7:1) |

O sistema já era coerente no material original e agora está explícito: cada
ground usa o acento que serve a ele. **Trocar um pelo outro quebra o
contraste** — o terracota sobre escuro dá 3,4:1.

Note a inversão em relação ao turquesa: o turquesa é claro (luminância 0,514) e
por isso virava chip com texto escuro; o terracota é escuro e vira chip com
texto creme.

### A tipografia: Charter, e o que ela custou

Os PDFs saíram em DejaVu Serif, mas isso é fallback do gerador e não escolha —
a intenção era serifa para texto corrido. As peças usam **Bitstream Charter**,
que o Pillow carrega mesmo sendo Type1 (`.pfb`), conferido.

A serifa teve um preço medível e contraintuitivo. Sobre foto, os pixels de
miolo do texto caíram de **39.000 para 20.000**: a Charter tem traço modulado, e
os traços finos somem primeiro sobre fundo variado. A thumbnail saltou de 0–2%
de pixels ilegíveis para 12–16%.

Reforçar o halo não resolveu. O que resolveu foi **um contorno de 2px** — o
mesmo recurso que a legenda já usava, pelo mesmo motivo. O contorno devolve
massa ao traço fino, e é ele que torna a serifa viável sobre imagem.

A Inter não saiu: fica na legenda queimada e em texto pequeno sobre imagem em
movimento. A legenda validada em `docs/04` acima **não muda** por causa da marca.

### O validador precisou de três correções, todas porque mentia

`scripts/valida-marca.py` chegou ao número certo em quatro tentativas, e cada
erro vale registro porque é do tipo que passa despercebido:

1. **medir retângulos** em vez dos pixels do texto — comparava contra o pixel
   mais claro de áreas onde não havia texto nenhum;
2. **contar a borda de antialiasing** — meio-tom entre texto e fundo, por
   definição de baixo contraste; acusava 7,8% de ilegibilidade no post com o
   texto a 17:1 sobre fundo sólido. Resolvido com erosão da máscara;
3. **contar o contorno como texto** — o contorno é escuro de propósito e não
   precisa contrastar com nada. Contando-o, *pôr* contorno "piorava" o número de
   15% para 19%, exatamente ao tornar a peça mais legível;
4. **inferir a claridade da peça pela mediana** — no post a foto ocupa 58% da
   altura e, num frame escuro, a peça inteira era classificada como escura e
   sumia da medição. A claridade passou a ser declarada por peça.

A lição que generaliza: **uma métrica que não distingue miolo, borda e contorno
mede a tinta, não a leitura.** E o sinal de que ela está errada é justamente uma
melhoria real piorar o número.

O relatório final separa dois caminhos, porque as peças chegam à legibilidade
por rotas diferentes: sobre foto o texto é julgado **contra o próprio contorno**,
que é com quem faz fronteira; sobre fundo sólido, contra o fundo. Exigir os dois
reprovava o post, que está a 15,7:1.

## Duas soluções, uma direção

Ao consolidar, em 30/08/2026, apareceu uma sobreposição: `scripts/capa_arte.py`,
escrito noutra sessão, gera capa 1280x720 e 1080x1920 — **as mesmas peças** que
o `scripts/marca.py`. Cada um com sua tipografia e sua paleta, e nenhum dos dois
lê o do outro. O `capa_arte.py` tem as cores escritas dentro do código.

**Qual é o canônico está decidido:** o `capa_arte.py` foi solução pontual, feita
para destravar as primeiras publicações, e cumpriu o papel. Daqui em diante o
sistema é `marca/tokens.toml` + `scripts/marca.py`, e é dele que os próximos
episódios partem.

A notícia boa é o quanto as duas concordam. Partindo de fontes diferentes — o
guia escrito, num caso; o violão filmado, no outro — chegaram a quase a mesma
paleta:

| | `marca.py` (do guia) | `capa_arte.py` (do violão) | distância RGB |
|---|---|---|---|
| fundo | `#181510` | `#16110E` | 5 |
| texto | `#F5F1EA` | `#F7F3EC` | 3 |
| acento claro | `#DEA87E` (26°) | `#E8A857` (34°) | 40 |

Fundo e texto são praticamente o mesmo par. O acento difere de 8° em matiz e de
0,19 em saturação: o âmbar do violão é mais dourado, o salmão do guia é mais
rosado. **É ajuste fino, não divergência de direção.** As duas sessões também
escolheram serifa por conta própria — EB Garamond de um lado, Bitstream Charter
do outro.

Isso não deve ficar assim. Duas soluções para o mesmo problema envelhecem mal:
alguém muda a cor num lugar e a outra peça continua na cor velha, sem erro.

**O que fazer quando o `capa_arte.py` for reusado:** fazê-lo ler
`marca/tokens.toml` em vez de carregar cor e fonte no código. Enquanto não for
tocado, ele fica como está — os vídeos que ele gerou já estão no ar e não há
motivo para mexer neles.

A convergência independente é, por si, o argumento mais forte que esta
identidade tem: duas análises separadas, sobre materiais diferentes, apontaram
para o mesmo lugar.

## O que falta

- [ ] Medir a safe area no aplicativo com o gabarito, e trocar o palpite de
      25% pelo número medido.
- [ ] Validar o 9:16 sobre um corte vertical de verdade. O que foi validado
      aqui usa um crop central do 16:9, que serve para medir contraste mas não
      é o enquadramento que vai ao ar.
- [ ] Templates de thumbnail (1280x720), post de feed (1080x1350) e story.
      Dependem de decisões que ainda não existem: uso de rosto, quantidade de
      texto, e se o canal tem nome fechado.
- [ ] A paleta hoje é só branco e quase-preto — o suficiente para legenda, não
      para thumbnail e post. Uma cor de destaque precisa ser escolhida antes
      dos templates, e escolhida contra os frames reais, que são dominados por
      parede clara e violão sunburst.
