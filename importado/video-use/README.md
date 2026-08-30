# importado/video-use — área de teste

Código trazido do https://github.com/browser-use/video-use (MIT, commit
`9575612`). **Não faz parte do fluxo oficial.** Nada aqui é chamado pelos
scripts de `scripts/`, e nada daqui migra para lá sem medição registrada.

A decisão, o que foi importado, o que está na fila e o que foi recusado
estão em **`docs/02-import-video-use.md`**. Leia esse arquivo antes de
mexer aqui.

## Conteúdo

- `timeline.py` — filmstrip + forma de onda + palavras numa PNG, para um
  intervalo do vídeo. Porte de `helpers/timeline_view.py`, adaptado para
  o nosso `.words.tsv` e `segmentos.txt`.
- `LICENSE-upstream` — a licença MIT original, obrigatória para a atribuição.

## Uso

```bash
cd ~/video && source .venv/bin/activate
python importado/video-use/timeline.py out/ep00_audio.mp4 32 43
# -> work/timeline/ep00_32-43.png
```

Resolve `out/<base>.words.tsv` e `out/<base>.segmentos.txt` sozinho, tirando
do nome do vídeo os sufixos `_norm`, `_audio`, `_final` e `_legendado`.
Sem os sidecars ele ainda roda, só sem rótulo de palavra nem sombreado.

Dependência nova no venv: `Pillow`.
