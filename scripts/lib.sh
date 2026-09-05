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
