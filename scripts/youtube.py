#!/usr/bin/env python3
"""Escreve metadados de vídeos do YouTube pela Data API v3.

Por que existe: título, descrição e tags são texto derivado do mesmo trabalho
que já está no disco. Digitar isso no Studio a cada episódio é tarefa
determinística — e o princípio 3 do ~/video/CLAUDE.md diz que tarefa
determinística vira script.

O QUE ESTE SCRIPT NÃO FAZ SOZINHO: publicar. Ele SOBE (sempre privado),
mas mudar a visibilidade é um
subcomando separado (`publica`), com confirmação, porque é a única ação aqui
que não dá para desfazer — vídeo que ficou público por 30 segundos pode ter
sido visto, indexado e notificado a inscritos.

Segredos ficam em ~/video/.secrets/, que está no .gitignore e em modo 700.
Nada de credencial é impresso, nem em erro.

--- ordem de uso ---------------------------------------------------------
  python scripts/youtube.py autoriza          # uma vez; abre o navegador
  python scripts/youtube.py sobe video.mp4 meta.txt      # entra PRIVADO
  python scripts/youtube.py lista             # acha o ID do rascunho
  python scripts/youtube.py aplica ID meta.txt --seco    # mostra sem enviar
  python scripts/youtube.py aplica ID meta.txt
  python scripts/youtube.py capa   ID capa.jpg
  python scripts/youtube.py publica ID --como nao-listado

--- formato do arquivo de metadados --------------------------------------
  titulo: ...
  tags: a, b, c
  categoria: 10
  idioma: pt-BR
  idioma_audio: en
  ---
  (tudo daqui para baixo é a descrição, com quebras de linha preservadas)

--- custo de cota --------------------------------------------------------
  lista 1 · aplica 50 · capa 50 · publica 50 · exclui 50 · sobe 1600, contra
  10.000 por dia. Só o upload pesa, e ainda assim cabem seis por dia.
"""
import argparse, json, os, sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SEGREDOS = RAIZ / ".secrets"
CLIENTE = SEGREDOS / "client_secret.json"
TOKEN = SEGREDOS / "youtube_token.json"

# force-ssl cobre ler, escrever metadados e mandar capa. Não pede mais que isso.
ESCOPOS = ["https://www.googleapis.com/auth/youtube.force-ssl"]

LIMITE_TITULO = 100        # caracteres, limite duro da API
LIMITE_DESCRICAO = 5000
LIMITE_TAGS = 500          # soma dos caracteres de todas as tags

VISIBILIDADE = {"privado": "private", "nao-listado": "unlisted", "publico": "public"}


def morre(msg):
    print(f"erro: {msg}", file=sys.stderr)
    raise SystemExit(1)


def servico():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    if not TOKEN.exists():
        morre("sem token. Rode primeiro:  python scripts/youtube.py autoriza")
    cred = Credentials.from_authorized_user_file(str(TOKEN), ESCOPOS)
    if not cred.valid:
        if cred.expired and cred.refresh_token:
            cred.refresh(Request())
            TOKEN.write_text(cred.to_json()); TOKEN.chmod(0o600)
        else:
            morre("token inválido ou revogado. Rode 'autoriza' de novo.")
    return build("youtube", "v3", credentials=cred, cache_discovery=False)


# --------------------------------------------------------------- autoriza
def cmd_autoriza(a):
    from google_auth_oauthlib.flow import InstalledAppFlow
    if not CLIENTE.exists():
        morre(f"falta {CLIENTE}\n"
              "  Console do Google Cloud -> Credenciais -> ID do cliente OAuth\n"
              "  -> tipo 'App para computador' -> baixar o JSON para esse caminho.")
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENTE), ESCOPOS)
    cred = flow.run_local_server(port=0, prompt="consent",
                                 authorization_prompt_message="Abrindo o navegador para autorizar…\n{url}",
                                 success_message="Autorizado. Pode fechar esta aba e voltar ao terminal.")
    TOKEN.write_text(cred.to_json()); TOKEN.chmod(0o600)
    print(f"token salvo em {TOKEN} (modo 600)")
    if not cred.refresh_token:
        print("AVISO: não veio refresh_token — a sessão vai expirar. "
              "Revogue o acesso do app na Conta Google e autorize de novo.")


# ------------------------------------------------------------------ lista
def cmd_lista(a):
    y = servico()
    canais = y.channels().list(part="contentDetails,snippet", mine=True).execute()
    if not canais.get("items"):
        morre("a conta autorizada não tem canal.")
    ch = canais["items"][0]
    envios = ch["contentDetails"]["relatedPlaylists"]["uploads"]
    print(f'canal: {ch["snippet"]["title"]}  ({ch["id"]})\n')

    itens, pag = [], None
    while len(itens) < a.quantos:
        r = y.playlistItems().list(part="contentDetails", playlistId=envios,
                                   maxResults=min(50, a.quantos - len(itens)),
                                   pageToken=pag).execute()
        itens += [i["contentDetails"]["videoId"] for i in r["items"]]
        pag = r.get("nextPageToken")
        if not pag:
            break
    if not itens:
        print("nenhum vídeo. Se você acabou de subir e ele está como RASCUNHO no\n"
              "Studio, termine o assistente de upload (basta salvar como Privado):\n"
              "rascunho que não foi finalizado não existe para a API.")
        return

    det = y.videos().list(part="snippet,status,contentDetails",
                          id=",".join(itens)).execute()
    print(f'{"ID":13s} {"visib.":10s} {"duração":9s} {"enviado em":11s} título')
    for v in det["items"]:
        s, st = v["snippet"], v["status"]
        print(f'{v["id"]:13s} {st["privacyStatus"]:10s} '
              f'{v["contentDetails"]["duration"].replace("PT",""):9s} '
              f'{s["publishedAt"][:10]:11s} {s["title"][:52]}')


# ------------------------------------------------------------------- sobe
# O upload ficou FORA deste script até 08/09/2026, com o argumento de que o
# Studio dá barra de progresso e retomada, que a API não daria. Dois fatos
# derrubaram isso: upload resumível com callback dá as duas coisas — é o que
# está aqui —, e num Short de algumas dezenas de MB a retomada nunca chega a
# ser exercida.
#
# O que NÃO mudou: sobe sempre PRIVADO. Ir a público continua sendo
# `publica`, com --sim. Subir e publicar são ações diferentes e só uma delas
# é irreversível.
#
# `selfDeclaredMadeForKids: False` vai explícito. O default chega ligado sem
# avisar — foi o que aconteceu no like-a-stone — e vídeo marcado como
# infantil perde comentário, notificação, playlist, telas finais e cards.
#
# Cota: 1600 unidades contra 10.000/dia, ou seis uploads por dia.
CHUNK = 8 * 1024 * 1024


def cmd_sobe(a):
    from googleapiclient.http import MediaFileUpload
    p = Path(a.arquivo)
    if not p.exists():
        morre(f"não achei {p}")

    if a.como_o:
        # Reaproveita o snippet de um vídeo que já está no ar. Existe porque
        # o texto costuma ser editado no Studio depois de publicado, e
        # redigitá-lo aqui é exatamente onde a versão boa se perde.
        y = servico()
        it = y.videos().list(part="snippet", id=a.como_o).execute().get("items")
        if not it:
            morre(f"vídeo {a.como_o} não encontrado nesta conta.")
        s = it[0]["snippet"]
        m = {"titulo": s["title"], "descricao": s.get("description", ""),
             "tags": s.get("tags", []), "categoria": s.get("categoryId", "10"),
             "idioma": s.get("defaultLanguage"),
             "idioma_audio": s.get("defaultAudioLanguage")}
        print(f"metadados copiados de {a.como_o}")
    else:
        if not a.meta:
            morre("informe um arquivo de metadados, ou --como-o <ID> para "
                  "copiar os de um vídeo que já está no ar")
        m = le_meta(a.meta)
        y = None
    for e in confere_limites(m):
        morre(e)

    corpo = {
        "snippet": {"title": m["titulo"], "description": m["descricao"],
                    "tags": m["tags"], "categoryId": m.get("categoria", "10")},
        "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": False,
                   "license": "youtube", "embeddable": True},
    }
    for chave, campo in (("idioma", "defaultLanguage"),
                         ("idioma_audio", "defaultAudioLanguage")):
        if m.get(chave):
            corpo["snippet"][campo] = m[chave]

    mb = p.stat().st_size / 1048576
    print(f"arquivo    {p.name}  ({mb:.1f} MB)")
    print(f'título     {m["titulo"]}')
    print(f'tags       {", ".join(m["tags"]) or "—"}')
    print(f'categoria  {corpo["snippet"]["categoryId"]}   '
          f'idioma {corpo["snippet"].get("defaultLanguage", "—")}')
    print(f'descrição  {len(m["descricao"])} caracteres')
    print("visibilidade  private   ·   feito para crianças  False")
    if a.seco:
        print("\n--- descrição que seria enviada ---")
        print(m["descricao"])
        print("\n(seco: nada foi enviado)")
        return

    y = y or servico()
    req = y.videos().insert(
        part="snippet,status", body=corpo,
        media_body=MediaFileUpload(str(p), chunksize=CHUNK, resumable=True))
    print()
    resp = None
    while resp is None:
        estado, resp = req.next_chunk()
        if estado:
            print(f"\r  enviando… {int(estado.progress() * 100):3d}%",
                  end="", flush=True)
    print("\r  enviando… 100%")
    vid = resp["id"]
    print(f'\nsubiu como PRIVADO:  {vid}')
    print(f"  https://youtu.be/{vid}")
    print(f'  processamento: {resp["status"].get("uploadStatus")}')
    print("\nDepois:")
    print(f"  python scripts/youtube.py capa {vid} <capa.jpg>")
    print(f"  python scripts/youtube.py publica {vid} --como nao-listado")


# ----------------------------------------------------------------- exclui
def cmd_exclui(a):
    """Apaga um vídeo do canal. NÃO TEM VOLTA — o YouTube não tem lixeira.

    Exige --sim pelo mesmo motivo que `publica --como publico` exige, e
    imprime o que vai apagar ANTES de apagar: o alvo é um ID de onze
    caracteres, e dois IDs do mesmo episódio diferem por um caractere.
    """
    y = servico()
    it = y.videos().list(part="snippet,status,fileDetails", id=a.id).execute().get("items")
    if not it:
        morre(f"vídeo {a.id} não encontrado nesta conta.")
    v = it[0]
    vs = (v.get("fileDetails", {}).get("videoStreams") or [{}])[0]
    print(f'{a.id}  "{v["snippet"]["title"]}"')
    print(f'  visibilidade {v["status"]["privacyStatus"]}   '
          f'fonte {vs.get("widthPixels", "?")}x{vs.get("heightPixels", "?")}   '
          f'enviado em {v["snippet"]["publishedAt"][:10]}')
    if not a.sim:
        print("\n  Apagar é IRREVERSÍVEL: o YouTube não tem lixeira para vídeo,\n"
              "  e o ID some junto (links e incorporações quebram).\n"
              "  Repita com --sim para confirmar.")
        raise SystemExit(2)
    y.videos().delete(id=a.id).execute()
    print("\n  excluído.")


# ----------------------------------------------------------------- aplica
def le_meta(caminho):
    txt = Path(caminho).read_text(encoding="utf-8")
    if "\n---\n" not in txt:
        morre(f"{caminho}: falta a linha '---' separando o cabeçalho da descrição")
    cab, desc = txt.split("\n---\n", 1)
    m = {}
    for linha in cab.splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#"):
            continue
        if ":" not in linha:
            morre(f"cabeçalho sem ':' -> {linha!r}")
        k, v = linha.split(":", 1)
        m[k.strip()] = v.strip()
    m["descricao"] = desc.strip("\n")
    faltando = {"titulo"} - set(m)
    if faltando:
        morre(f"falta no cabeçalho: {', '.join(sorted(faltando))}")
    m["tags"] = [t.strip() for t in m.get("tags", "").split(",") if t.strip()]
    return m


def confere_limites(m):
    erros = []
    if len(m["titulo"]) > LIMITE_TITULO:
        erros.append(f'título tem {len(m["titulo"])} caracteres (máx {LIMITE_TITULO})')
    if "<" in m["titulo"] or ">" in m["titulo"]:
        erros.append("título tem < ou >, que a API recusa")
    if len(m["descricao"]) > LIMITE_DESCRICAO:
        erros.append(f'descrição tem {len(m["descricao"])} caracteres (máx {LIMITE_DESCRICAO})')
    soma = sum(len(t) for t in m["tags"])
    if soma > LIMITE_TAGS:
        erros.append(f"tags somam {soma} caracteres (máx {LIMITE_TAGS})")
    for t in m["tags"]:
        if len(t) > 30:
            erros.append(f"tag longa demais: {t!r}")
    return erros


def cmd_aplica(a):
    m = le_meta(a.meta)
    for e in confere_limites(m):
        morre(e)
    y = servico()
    atual = y.videos().list(part="snippet,status", id=a.id).execute()
    if not atual.get("items"):
        morre(f"vídeo {a.id} não encontrado nesta conta.")
    v = atual["items"][0]
    snip = dict(v["snippet"])          # A API SOBRESCREVE a parte inteira:
                                       # campo que não for reenviado é APAGADO.
                                       # Por isso parte-se do snippet atual.
    novo = dict(snip)
    novo["title"] = m["titulo"]
    novo["description"] = m["descricao"]
    novo["tags"] = m["tags"] or snip.get("tags", [])
    novo["categoryId"] = m.get("categoria", snip.get("categoryId", "10"))
    if m.get("idioma"):
        novo["defaultLanguage"] = m["idioma"]
    if m.get("idioma_audio"):
        novo["defaultAudioLanguage"] = m["idioma_audio"]

    print(f'vídeo   {a.id}   (visibilidade atual: {v["status"]["privacyStatus"]})')
    for campo, antes, depois in (
            ("título", snip.get("title", ""), novo["title"]),
            ("categoria", snip.get("categoryId", ""), novo["categoryId"]),
            ("idioma", snip.get("defaultLanguage", "—"), novo.get("defaultLanguage", "—")),
            ("tags", ", ".join(snip.get("tags", [])) or "—", ", ".join(novo["tags"]))):
        if str(antes) != str(depois):
            print(f"  {campo:10s} {antes!s:.60}\n  {'':10s}   -> {depois!s:.60}")
    print(f'  descrição  {len(snip.get("description",""))} -> {len(novo["description"])} caracteres')

    if a.seco:
        print("\n--- descrição que seria enviada ---")
        print(novo["description"])
        print("\n(seco: nada foi enviado)")
        return
    y.videos().update(part="snippet", body={"id": a.id, "snippet": novo}).execute()
    print("\naplicado. A visibilidade NÃO foi tocada.")


# ------------------------------------------------------------------- capa
def cmd_capa(a):
    from googleapiclient.http import MediaFileUpload
    p = Path(a.imagem)
    if not p.exists():
        morre(f"não achei {p}")
    mb = p.stat().st_size / 1048576
    if mb > 2:
        morre(f"{p.name} tem {mb:.1f} MB; o limite do YouTube é 2 MB")
    y = servico()
    y.thumbnails().set(videoId=a.id,
                       media_body=MediaFileUpload(str(p))).execute()
    print(f"capa enviada ({mb:.2f} MB)")


# --------------------------------------------------------------- infantil
# Campos de `status` que a API aceita escrever. Mandar um read-only junto
# (madeForKids, uploadStatus) faz a chamada falhar.
STATUS_GRAVAVEIS = ("privacyStatus", "license", "embeddable",
                    "publicStatsViewable", "selfDeclaredMadeForKids")


def cmd_infantil(a):
    """Declara se o vídeo é 'feito para crianças'.

    Não é uma caixinha qualquer: marcado como infantil, o YouTube DESLIGA
    comentários, notificação para inscritos, salvar em playlist, telas finais,
    cards e anúncio personalizado. E é declaração legal (COPPA/FTC), então quem
    responde é o autor — o script só escreve o que mandarem.
    """
    alvo = a.como == "sim"
    y = servico()
    v = y.videos().list(part="status,snippet", id=a.id).execute()["items"][0]
    st = v["status"]
    agora = st.get("selfDeclaredMadeForKids")
    print(f'{a.id}  "{v["snippet"]["title"]}"')
    print(f"  feito para crianças: {agora}  ->  {alvo}")
    if agora == alvo:
        print("  já está assim; nada a fazer."); return
    novo = {k: st[k] for k in STATUS_GRAVAVEIS if k in st}
    novo["selfDeclaredMadeForKids"] = alvo
    y.videos().update(part="status", body={"id": a.id, "status": novo}).execute()
    dep = y.videos().list(part="status", id=a.id).execute()["items"][0]["status"]
    print(f'  gravado. madeForKids agora: {dep.get("madeForKids")}')
    if not alvo:
        print("  comentários voltam a ser possíveis; o liga/desliga fica no Studio,\n"
              "  porque a Data API v3 não expõe campo de comentário nenhum.")


# ---------------------------------------------------------------- publica
def cmd_publica(a):
    alvo = VISIBILIDADE[a.como]
    y = servico()
    atual = y.videos().list(part="status,snippet", id=a.id).execute()
    if not atual.get("items"):
        morre(f"vídeo {a.id} não encontrado.")
    v = atual["items"][0]
    agora = v["status"]["privacyStatus"]
    print(f'{a.id}  "{v["snippet"]["title"]}"')
    print(f"  {agora}  ->  {alvo}")
    if agora == alvo:
        print("  já está assim; nada a fazer."); return
    if alvo == "public" and not a.sim:
        print("\n  'public' é irreversível na prática: o vídeo aparece na busca,\n"
              "  no feed e notifica inscritos. Repita com --sim para confirmar.")
        raise SystemExit(2)
    st = dict(v["status"]); st["privacyStatus"] = alvo
    y.videos().update(part="status", body={"id": a.id, "status": st}).execute()
    print("  feito.")


# -------------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("autoriza", help="fluxo OAuth; abre o navegador").set_defaults(f=cmd_autoriza)

    s = sub.add_parser("lista", help="lista os vídeos do canal")
    s.add_argument("--quantos", type=int, default=15)
    s.set_defaults(f=cmd_lista)

    s = sub.add_parser("aplica", help="escreve título, descrição, tags e idioma")
    s.add_argument("id"); s.add_argument("meta")
    s.add_argument("--seco", action="store_true", help="mostra o que faria, sem enviar")
    s.set_defaults(f=cmd_aplica)

    s = sub.add_parser("sobe", help="envia o arquivo de vídeo; entra sempre como PRIVADO")
    s.add_argument("arquivo")
    s.add_argument("meta", nargs="?", help="arquivo de metadados; dispensável com --como-o")
    s.add_argument("--como-o", metavar="ID",
                   help="copia título, descrição, tags e idioma de um vídeo já no ar")
    s.add_argument("--seco", action="store_true", help="mostra o que faria, sem enviar")
    s.set_defaults(f=cmd_sobe)

    s = sub.add_parser("capa", help="envia a miniatura")
    s.add_argument("id"); s.add_argument("imagem")
    s.set_defaults(f=cmd_capa)

    s = sub.add_parser("infantil", help="declara se é 'feito para crianças'")
    s.add_argument("id")
    s.add_argument("--como", choices=("sim", "nao"), required=True)
    s.set_defaults(f=cmd_infantil)

    s = sub.add_parser("exclui", help="apaga um vídeo do canal (irreversível)")
    s.add_argument("id")
    s.add_argument("--sim", action="store_true", help="confirma a exclusão")
    s.set_defaults(f=cmd_exclui)

    s = sub.add_parser("publica", help="muda a visibilidade")
    s.add_argument("id")
    s.add_argument("--como", choices=sorted(VISIBILIDADE), required=True)
    s.add_argument("--sim", action="store_true", help="confirma a ida para público")
    s.set_defaults(f=cmd_publica)

    a = p.parse_args()
    try:
        a.f(a)
    except Exception as ex:
        from googleapiclient.errors import HttpError
        if isinstance(ex, HttpError):
            try:
                d = json.loads(ex.content)["error"]
                morre(f'API {d.get("code")}: {d.get("message")}')
            except Exception:
                morre(f"API: {ex}")
        raise


if __name__ == "__main__":
    main()
