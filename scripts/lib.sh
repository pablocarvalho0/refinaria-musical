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
