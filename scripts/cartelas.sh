#!/usr/bin/env bash
# Sobrepõe as cartelas de abertura e de créditos a um vídeo e fecha com
# fade-out de imagem.
#
# O áudio é COPIADO, sempre. Cartela é trabalho de imagem; reencodar o áudio
# aqui empilharia uma geração de AAC de graça, e no fluxo deste projeto quem
# produz áudio é o audio.sh, sozinho.
#
# Uso:
#   ./scripts/cartelas.sh ENTRADA.mp4 \
#       --titulo "A Hard Day's Night" --autoria "Lennon–McCartney" --ano 1964 \
#       --papeis "produção, mixagem e execução" [--rotulo cover] \
#       [--atraso 25] [--formato 9x16] [--saida work/nome.mp4] [--seco]
#
# --atraso move só a cartela de abertura; a de créditos é sempre ancorada no
# fim do vídeo, porque é lá que ela faz sentido.
#
# Tudo o que é aparência (tamanhos, cores, fontes, força do scrim, duração dos
# fades, quanto tempo cada cartela fica em tela) vem de marca/tokens.toml.
# Aqui só entram os textos do episódio e os caminhos.

set -euo pipefail
source "$(dirname "$(readlink -f "$0")")/lib.sh"

RAIZ="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
PY="${PY:-python3}"

ENTRADA=""; SAIDA=""; TITULO=""; AUTORIA=""; ANO=""
ROTULO="cover"; PAPEIS="produção, mixagem e execução"; FORMATO="9x16"; SECO=0
ATRASO=""   # override do cartela.abertura.atraso, em segundos

while (( $# )); do
  case "$1" in
    --titulo)  TITULO="$2"; shift 2 ;;
    --autoria) AUTORIA="$2"; shift 2 ;;
    --ano)     ANO="$2"; shift 2 ;;
    --rotulo)  ROTULO="$2"; shift 2 ;;
    --papeis)  PAPEIS="$2"; shift 2 ;;
    --formato) FORMATO="$2"; shift 2 ;;
    --atraso)  ATRASO="$2"; shift 2 ;;
    --saida)   SAIDA="$2"; shift 2 ;;
    --seco)    SECO=1; shift ;;
    -*)        echo "opção desconhecida: $1" >&2; exit 2 ;;
    *)         ENTRADA="$1"; shift ;;
  esac
done

[[ -n "$ENTRADA" && -f "$ENTRADA" ]] || { echo "uso: $0 ENTRADA.mp4 --titulo ... --autoria ..." >&2; exit 2; }
[[ -n "$TITULO"  ]] || { echo "--titulo é obrigatório" >&2; exit 2; }
[[ -n "$AUTORIA" ]] || { echo "--autoria é obrigatório: num cover o crédito de composição não é opcional" >&2; exit 2; }

BASE="$(basename "${ENTRADA%.*}")"
[[ -n "$SAIDA" ]] || SAIDA="$RAIZ/work/${BASE}_video.mp4"
PREFIXO="$RAIZ/work/${BASE}"

# --------------------------------------------------------------------------
# O que o arquivo é. A orientação não aparece na listagem e a distorção de
# vertical não dá erro — daí o resumo impresso sempre.
# --------------------------------------------------------------------------
geometria_video "$ENTRADA"
geometria_resumo

DUR=$(ffprobe -v error -select_streams v:0 -show_entries stream=duration \
      -of default=nw=1:nk=1 "$ENTRADA")
NBF=$(ffprobe -v error -select_streams v:0 -show_entries stream=nb_frames \
      -of default=nw=1:nk=1 "$ENTRADA")
FPS=$(ffprobe -v error -select_streams v:0 -show_entries stream=r_frame_rate \
      -of default=nw=1:nk=1 "$ENTRADA")

# --------------------------------------------------------------------------
# Os tempos saem dos tokens, não daqui. Um episódio mais curto que a soma das
# duas cartelas é erro de entrada, não de arredondamento — por isso a conta
# reclama em vez de sobrepor as duas.
# --------------------------------------------------------------------------
TEMPOS=$("$PY" - "$RAIZ" "$DUR" "${ATRASO:-}" <<'PYEOF'
import sys, pathlib, tomllib
raiz, dur = pathlib.Path(sys.argv[1]), float(sys.argv[2])
with (raiz / "marca" / "tokens.toml").open("rb") as f:
    t = tomllib.load(f)["cartela"]
# O token diz quando a abertura entra por padrão; o episódio pode discordar.
# No improviso_3 ela entra aos 25s, onde a fala acaba e o violão começa —
# esse instante é do episódio, não da marca, e por isso é override de linha
# de comando e não edição do tokens.toml.
a0 = float(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3] else t["abertura"]["atraso"]
if a0 < 0 or a0 >= dur:
    sys.exit(f"--atraso {a0}s não cabe num vídeo de {dur:.2f}s")
a1 = a0 + t["abertura"]["duracao"]
c0 = dur - t["creditos"]["duracao"]
if c0 <= a1:
    sys.exit(f"o vídeo tem {dur:.2f}s e as duas cartelas pedem "
             f"{a1 + t['creditos']['duracao']:.2f}s sem se encostar")
vfs = dur - t["fade_video_saida"]
if vfs <= c0:
    sys.exit("o fade-out de imagem começaria antes da cartela de créditos")
print(f"{a0:.3f} {a1:.3f} {a1 - t['fade_saida']:.3f} {c0:.3f} {vfs:.3f} "
      f"{t['fade_entrada']:.3f} {t['fade_video_saida']:.3f} {dur + 1:.3f}")
PYEOF
) || exit 1
read -r A0 A1 AFS C0 VFS FE VFD DUR_PNG <<<"$TEMPOS"

echo "==> Cartelas"
echo "    abertura : entra em ${A0}s, sai em ${A1}s (fade-out a partir de ${AFS}s)"
echo "    créditos : entra em ${C0}s e fica até o fim"
echo "    fade-out de imagem a partir de ${VFS}s"

# --------------------------------------------------------------------------
# Desenho. PNG com alfa, não drawtext: a Charter é Type1, o drawtext lida mal
# com ela, e um '%' solto no filtergraph descarta o rótulo inteiro com um
# warning fácil de perder.
# --------------------------------------------------------------------------
"$PY" "$RAIZ/scripts/cartelas.py" \
  --titulo "$TITULO" --autoria "$AUTORIA" ${ANO:+--ano "$ANO"} \
  --rotulo "$ROTULO" --papeis "$PAPEIS" --formato "$FORMATO" \
  --prefixo "$PREFIXO" --sem-texto

ABERT="$PREFIXO.abertura.png"
CRED="$PREFIXO.creditos.png"

# --------------------------------------------------------------------------
# Render
#
# Uma entrada por cartela, e nenhuma entrada reusada em dois ramos: é o
# padrão que enfileira frames decodificados até estourar a memória (ver
# "O corte que derrubava a IDE" no CLAUDE.md).
#
# `enable=` faz o overlay compor só na janela da cartela; fora dela o quadro
# passa direto. O `fade ... :alpha=1` é multiplicativo sobre o alfa que já
# existe, então o degradê do scrim sobrevive ao fade em vez de ser achatado.
#
# O fade-out de imagem vem DEPOIS dos dois overlays, de propósito: assim ele
# leva a cartela de créditos junto para o preto, em vez de apagar o vídeo e
# deixar o texto boiando.
# --------------------------------------------------------------------------
FC="[1:v]format=rgba,fade=t=in:st=${A0}:d=${FE}:alpha=1,"
FC+="fade=t=out:st=${AFS}:d=${FE}:alpha=1[ab];"
FC+="[2:v]format=rgba,fade=t=in:st=${C0}:d=${FE}:alpha=1[cb];"
FC+="[0:v][ab]overlay=0:0:format=auto:enable='between(t,${A0},${A1})'[v1];"
FC+="[v1][cb]overlay=0:0:format=auto:enable='gte(t,${C0})'[v2];"
FC+="[v2]fade=t=out:st=${VFS}:d=${VFD},format=yuv420p,setsar=1[v]"

if (( SECO )); then
  echo "==> --seco: nada foi renderizado. Filtro que seria usado:"
  echo "$FC" | tr ';' '\n'
  exit 0
fi

mkdir -p "$(dirname "$SAIDA")"
ffmpeg_lim -nostdin -hide_banner -y \
  -i "$ENTRADA" \
  -loop 1 -framerate "$FPS" -t "$DUR_PNG" -i "$ABERT" \
  -loop 1 -framerate "$FPS" -t "$DUR_PNG" -i "$CRED" \
  -filter_complex "$FC" \
  -map "[v]" -map 0:a \
  -c:v libx264 -crf 20 -preset fast -pix_fmt yuv420p -r "$FPS" \
  -frames:v "$NBF" \
  -c:a copy -metadata:s:a:0 language=por \
  -movflags +faststart \
  "$SAIDA"

echo "==> $SAIDA"
ffprobe -v error -select_streams v:0 \
  -show_entries stream=width,height,r_frame_rate,nb_frames,pix_fmt,sample_aspect_ratio \
  -of default=nw=1 "$SAIDA"
