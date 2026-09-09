#!/usr/bin/env bash
# Funções compartilhadas pelos scripts do pipeline.
#
# Carregue com:  source "$(dirname "$(readlink -f "$0")")/lib.sh"

# ---------------------------------------------------------------------
# ffmpeg dentro de um cgroup com teto de memória
#
# Em 30/08/2026 o corta.sh derrubou a IDE três vezes seguidas (10:57,
# 13:37 e 13:42). O ffmpeg crescia até 12 GB numa máquina de 15 GB, o
# kernel disparava o OOM killer, e a IDE morria junto — não por bug dela.
# Tudo que a IDE abre, inclusive o terminal e os processos disparados
# nele, vive no mesmo scope do systemd, e esse scope tem OOMPolicy=stop:
# basta UM processo lá dentro ser morto pelo OOM killer para o systemd
# derrubar o scope inteiro. Os três scopes falhados batem no segundo com
# os três OOM kills.
#
# Rodar o ffmpeg no próprio scope inverte isso: se estourar, morre só o
# encode, com mensagem legível, e quem chamou continua de pé. Vale para a
# IDE e para o terminal comum — o OOM de 12 GB era global, não do cgroup,
# então mataria a sessão de qualquer jeito.
#
# MemorySwapMax=0 é o que faz falhar rápido: sem ele a máquina passa
# minutos swapando, com o desktop travado, antes de alguém morrer.
#
# MEM_MAX é ajustável por ambiente. 6G é folgado para este pipeline — o
# corte medido usa 1,2 GB e o encode do processa.sh fica na mesma ordem —
# e ainda deixa 9 GB para o resto da máquina.
#
# Sem systemd de usuário (container, ssh sem sessão) cai no ffmpeg puro:
# perde a rede de proteção, mas não impede o trabalho de rodar.
# ---------------------------------------------------------------------

MEM_MAX="${MEM_MAX:-6G}"

# Detectado uma vez, na carga: o gerenciador de usuário responde?
if [[ "${SEM_LIMITE:-0}" != "1" ]] \
   && command -v systemd-run >/dev/null 2>&1 \
   && systemctl --user show --property=Version >/dev/null 2>&1; then
  FFMPEG_COM_TETO=1
else
  FFMPEG_COM_TETO=0
  [[ "${SEM_LIMITE:-0}" == "1" ]] \
    || echo "aviso: systemd de usuário indisponível — ffmpeg roda sem teto de memória" >&2
fi

ffmpeg_lim() {
  local rc=0
  if [[ "$FFMPEG_COM_TETO" == "1" ]]; then
    systemd-run --user --scope --quiet --collect \
      -p MemoryMax="$MEM_MAX" -p MemorySwapMax=0 \
      -- ffmpeg "$@" || rc=$?
  else
    ffmpeg "$@" || rc=$?
  fi

  if (( rc != 0 )); then
    echo >&2
    echo "ffmpeg falhou (código $rc)." >&2
    if [[ "$FFMPEG_COM_TETO" == "1" ]]; then
      echo "Se foi estouro de memória, o teto era MEM_MAX=$MEM_MAX." >&2
      echo "Confira com:  journalctl --user -n 20 | grep -i oom" >&2
      echo "Para dar mais folga:  MEM_MAX=10G $0 ..." >&2
      echo "Mas antes desconfie do grafo de filtros: reusar a mesma" >&2
      echo "entrada em vários ramos enfileira frames decodificados." >&2
    fi
    return $rc
  fi
}

# ---------------------------------------------------------------------
# Geometria de entrada: orientação, rotação e o alvo do encode
#
# Em 05/09/2026 entraram no inbox dois vídeos gravados com o celular em
# pé (rotation=-90). O processa.sh tinha scale=1920:1080 fixo, e o modo
# de falha é silencioso: o ffmpeg aplica a rotação dos metadados ANTES
# dos filtros (autorotate), então o scale recebia um quadro 2160x3840 e
# o espremia num 16:9. Imagem deformada, código de saída 0, nenhum aviso.
#
# Ler width/height não detecta nada — os dois arquivos dizem 3840x2160.
# Quem manda é o side data 'rotation'; com ±90 as dimensões EXIBIDAS são
# as trocadas. É esse par que decide o alvo.
#
# Duas defesas, além de escolher a orientação certa:
#
#   force_original_aspect_ratio=decrease + pad — o alvo é sempre exato
#   (o concat exige), mas nada é esticado para chegar lá: sobra barra
#   preta. Para uma fonte 16:9 indo a 1920x1080 é no-op, custo zero;
#   para qualquer proporção torta é a diferença entre barra e distorção.
#
#   setsar=1 — força pixel quadrado. Um SAR diferente de 1 no master
#   atravessa o encode e o player estica na exibição, reproduzindo o
#   mesmo sintoma por outro caminho.
#
# Define, para quem chamou: GEO_W, GEO_H (exibidas), GEO_ROT, GEO_ORIENT
# ('horizontal'|'vertical'), GEO_ALVO_W, GEO_ALVO_H e GEO_VF.
#
# ORIENTACAO=h|v força o alvo, para quando o metadado mentir ou para
# gerar o vertical a partir de um master deitado.
# ---------------------------------------------------------------------

geometria_video() {
  local arq="$1"
  local w h rot

  # 'csv=p=0' NÃO serve aqui: num stream com side data o ffprobe emite a
  # coluna extra e devolve "3840," — a vírgula entra na variável e o
  # (( )) seguinte morre com 'operand expected'. O nk=1 devolve só o valor.
  local probe
  probe=$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height \
          -of default=nw=1:nk=1 "$arq" 2>/dev/null) || true
  w=$(sed -n 1p <<<"$probe" | tr -dc '0-9')
  h=$(sed -n 2p <<<"$probe" | tr -dc '0-9')

  [[ -n "$w" && -n "$h" ]] || { echo "sem stream de vídeo: $arq" >&2; return 1; }

  # side data é o formato atual; a tag 'rotate' é o legado de arquivos antigos.
  # O '|| true' é obrigatório: sob 'set -o pipefail' um grep sem match faz o
  # pipeline retornar 1, e o 'set -e' aborta o script inteiro — que foi
  # exatamente o que aconteceu no primeiro teste com material horizontal,
  # o caso em que NÃO existe rotação para achar.
  rot=$(ffprobe -v error -select_streams v:0 -show_entries stream_side_data=rotation \
        -of default=nw=1:nk=1 "$arq" 2>/dev/null | grep -oE '^-?[0-9]+' | head -1 || true)
  [[ -n "$rot" ]] || rot=$(ffprobe -v error -select_streams v:0 \
        -show_entries stream_tags=rotate -of default=nw=1:nk=1 "$arq" 2>/dev/null \
        | grep -oE '^-?[0-9]+' | head -1 || true)
  [[ -n "$rot" ]] || rot=0

  GEO_ROT=$(( ((rot % 360) + 360) % 360 ))   # -90 e 270 são o mesmo giro

  # com ±90 o quadro chega ao filtro já girado: as dimensões úteis trocam
  if (( GEO_ROT == 90 || GEO_ROT == 270 )); then
    GEO_W="$h"; GEO_H="$w"
  else
    GEO_W="$w"; GEO_H="$h"
  fi

  case "${ORIENTACAO:-auto}" in
    h|H) GEO_ORIENT=horizontal ;;
    v|V) GEO_ORIENT=vertical ;;
    auto) if (( GEO_W >= GEO_H )); then GEO_ORIENT=horizontal
          else GEO_ORIENT=vertical; fi ;;
    *) echo "ORIENTACAO inválida: ${ORIENTACAO} (use h, v ou auto)" >&2; return 1 ;;
  esac

  if [[ "$GEO_ORIENT" == horizontal ]]; then
    GEO_ALVO_W=1920; GEO_ALVO_H=1080
  else
    GEO_ALVO_W=1080; GEO_ALVO_H=1920
  fi

  GEO_VF="scale=${GEO_ALVO_W}:${GEO_ALVO_H}:force_original_aspect_ratio=decrease:force_divisible_by=2"
  GEO_VF+=",pad=${GEO_ALVO_W}:${GEO_ALVO_H}:(ow-iw)/2:(oh-ih)/2"
  GEO_VF+=",setsar=1"
}

# Uma linha legível sobre o que foi detectado. Vale imprimir sempre: a
# distorção de vertical não dá erro, então o log é a única chance de
# alguém perceber que o alvo saiu errado.
geometria_resumo() {
  local proporcao aviso=""
  proporcao=$(awk -v w="$GEO_W" -v h="$GEO_H" 'BEGIN{printf "%.4f", w/h}')
  local alvo_prop
  alvo_prop=$(awk -v w="$GEO_ALVO_W" -v h="$GEO_ALVO_H" 'BEGIN{printf "%.4f", w/h}')
  awk -v a="$proporcao" -v b="$alvo_prop" 'BEGIN{exit !(a-b > 0.01 || b-a > 0.01)}' \
    && aviso="  (proporção difere do alvo — entra barra preta, não distorção)"

  echo "==> Geometria: ${GEO_W}x${GEO_H} exibidas, rotation=${GEO_ROT}° -> ${GEO_ORIENT}"
  echo "    Alvo: ${GEO_ALVO_W}x${GEO_ALVO_H}${aviso}"
}

# ---------------------------------------------------------------------
# Pasta de saída por projeto
#
# Em 05/09/2026 o out/ tinha 40 arquivos de 4 masters, e o improviso_4
# sozinho respondia por 8 deles: _v, _vg, .v1, .v2, .v3. O mesmo vídeo
# gera cortes diferentes e testes de dinâmica distintos, e o nome do
# arquivo era a única coisa separando um do outro. Publicar o errado é
# silencioso — só se percebe assistindo.
#
# A saída passa a ser out/<projeto>/, com o projeto derivado do caminho.
# Um nível só, de propósito: os sufixos de variante (_v, _cover, .v1) já
# distinguem dentro da pasta, e a transcrição, o .srt e o segmentos.txt
# são do episódio inteiro — não têm onde morar num segundo nível.
#
# A resolução tem quatro degraus, do mais explícito ao mais adivinhado:
#
#   1. $PROJETO, se estiver setado. É o escape hatch, como ORIENTACAO.
#   2. o caminho já está sob out/<X>/  ->  X. Cobre todo o meio do
#      fluxo: audio.sh, corta.sh e legenda.py recebem arquivos que o
#      passo anterior já colocou na pasta certa.
#   3. a maior pasta de out/ que prefixa o basename. É o que faz
#      work/improviso_4_v.wav voltar para out/improviso_4/, sem o work/
#      precisar mudar de forma.
#   4. o basename sem extensão e sem sufixo de etapa. Só sobra para a
#      primeira execução, com o master vindo do inbox — onde o nome
#      está limpo e o palpite é o certo.
#
# Nunca falha calado: quem chama imprime o projeto resolvido com
# projeto_resumo, porque escrever na pasta errada é exatamente o tipo de
# erro que só aparece três passos depois.
# ---------------------------------------------------------------------

# Seta PROJETO_NOME e PROJETO_ORIGEM, e ecoa o nome. As duas coisas
# porque há dois usos: $(projeto_de x) para quem só quer o valor, e a
# chamada direta de pasta_projeto, que precisa da ORIGEM para o log —
# e substituição de comando abre subshell, de onde variável não volta.
PROJETO_NOME=""; PROJETO_ORIGEM=""

projeto_de() {
  local caminho="$1"
  local raiz="${RAIZ_OUT:-$HOME/video/out}"

  # 1. explícito
  if [[ -n "${PROJETO:-}" ]]; then
    PROJETO_NOME="$PROJETO"; PROJETO_ORIGEM="variável PROJETO"
    echo "$PROJETO_NOME"; return
  fi

  local abs; abs=$(readlink -m "$caminho")

  # 2. já está dentro de out/<X>/
  if [[ "$abs" == "$raiz"/*/* ]]; then
    local resto="${abs#"$raiz"/}"
    PROJETO_NOME="${resto%%/*}"; PROJETO_ORIGEM="pasta de origem"
    echo "$PROJETO_NOME"; return
  fi

  local base; base=$(basename "$caminho"); base="${base%.*}"

  # 3. maior pasta existente que prefixa o basename
  local melhor="" cand nome
  if [[ -d "$raiz" ]]; then
    for cand in "$raiz"/*/; do
      [[ -d "$cand" ]] || continue
      nome=$(basename "$cand")
      [[ "$base" == "$nome" || "$base" == "$nome"_* || "$base" == "$nome".* ]] || continue
      (( ${#nome} > ${#melhor} )) && melhor="$nome"
    done
  fi
  if [[ -n "$melhor" ]]; then
    PROJETO_NOME="$melhor"; PROJETO_ORIGEM="pasta existente que prefixa o nome"
    echo "$PROJETO_NOME"; return
  fi

  # 4. basename sem sufixo de etapa
  #
  # Os sufixos com ponto importam tanto quanto os com underscore: sem
  # eles, ep00.16x9.ass abria uma pasta out/ep00.16x9/. O degrau só é
  # usado quando a pasta ainda não existe — ou seja, exatamente na
  # primeira execução, quando não há nada para corrigir o palpite.
  local antes
  while :; do
    antes="$base"
    base="${base%_norm}"; base="${base%_audio}"
    base="${base%_final}"; base="${base%_legendado}"; base="${base%_work48}"
    base="${base%.16x9}"; base="${base%.9x16}"
    base="${base%.words}"; base="${base%.segments}"; base="${base%.segmentos}"
    [[ "$base" =~ \.v[0-9]+$ ]] && base="${base%.*}"
    [[ "$base" == "$antes" ]] && break
  done
  PROJETO_NOME="$base"; PROJETO_ORIGEM="nome do arquivo"
  echo "$PROJETO_NOME"
}

# Resolve o projeto, cria a pasta e deixa PROJETO_DIR pronto.
# ---------------------------------------------------------------------
# Rodada de testes: RODADA=<slug> desvia a escrita para out/<ep>/testes/<slug>/
#
# Comparar variantes gera muito mais arquivo do que publicar uma. Em
# 05/09/2026 uma única rodada de quatro opções pôs dez arquivos em
# out/improviso_4/ — seis intermediários e quatro montagens —, ao lado do
# corte aprovado, e o nome voltou a ser a única coisa separando o que se
# publica do que se está julgando. É a mesma falha de 41 arquivos que
# criou a pasta por projeto, um nível abaixo.
#
# A separação NÃO contradiz o "um nível, não dois" daquela decisão. Lá o
# que se recusou foi uma pasta por ENTREGA, porque a transcrição, o .srt e
# o segmentos.txt são do episódio inteiro e não teriam onde morar. Aqui a
# pasta é por RODADA de teste, e é exatamente o material que NÃO é do
# episódio inteiro: renders descartáveis, que existem para serem
# comparados e depois apagados.
#
# Duas variáveis, de propósito:
#   PROJETO_RAIZ  out/<ep>/ — onde vivem os textos do episódio. Quem
#                 PROCURA insumo procura aqui, com ou sem rodada.
#   PROJETO_DIR   onde ESTA execução escreve. Igual à raiz, ou a pasta da
#                 rodada quando RODADA está setada.
#
# Confundir as duas é o que faria o audio.sh de uma rodada não achar o
# segmentos.txt do episódio e cair no modo errado sem avisar.
# ---------------------------------------------------------------------
pasta_projeto() {
  # sem $( ): a origem é setada dentro de projeto_de e subshell não devolve
  projeto_de "$1" >/dev/null
  PROJETO_RAIZ="${RAIZ_OUT:-$HOME/video/out}/$PROJETO_NOME"
  PROJETO_DIR="$PROJETO_RAIZ"
  if [[ -n "${RODADA:-}" ]]; then
    [[ "$RODADA" =~ ^[A-Za-z0-9._-]+$ && "$RODADA" != *..* ]] || {
      echo "RODADA inválida: '$RODADA' — só letras, números, . _ -" >&2; exit 2; }
    PROJETO_DIR="$PROJETO_RAIZ/testes/$RODADA"
  fi
  mkdir -p "$PROJETO_DIR"
}

projeto_resumo() {
  echo "==> Projeto: ${PROJETO_NOME}  (por ${PROJETO_ORIGEM})"
  if [[ -n "${RODADA:-}" ]]; then
    echo "    Rodada de teste: ${RODADA}  — NÃO é entregável"
    echo "    Saída em: out/${PROJETO_NOME}/testes/${RODADA}/"
  else
    echo "    Saída em: out/${PROJETO_NOME}/"
  fi
}
