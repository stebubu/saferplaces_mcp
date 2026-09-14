"""
Server MCP per le REST API di SaferPlaces (api.saferplaces.co)
==============================================================

Genera automaticamente i tool MCP a partire dalla specifica OpenAPI
e inietta le credenziali (user + token) nel body di ogni richiesta POST.

Requisiti:
    pip install fastmcp httpx

Configurazione:
    export SAFERPLACES_USER="il-tuo-nome-utente"
    export SAFERPLACES_TOKEN="il-tuo-token"

Avvio manuale (per test):
    python saferplaces_mcp.py
"""

import os
import json
import httpx
from fastmcp import FastMCP

BASE_URL = "https://api.saferplaces.co"
OPENAPI_URL = f"{BASE_URL}/openapi?f=json"

# Copia locale dello spec, con tutti i $ref esterni risolti/inlineati
# ("bundled"). Serve perché: (a) l'ambiente di build di FastMCP Cloud non
# ha accesso di rete in uscita durante l'introspezione del server, e (b) il
# parser OpenAPI usato da fastmcp non supporta comunque riferimenti esterni
# (es. verso schemas.opengis.net o api.saferplaces.co/schemas/...), solo
# quelli locali ("#/..."). Rigenerala con tools/bundle_openapi.py.
OPENAPI_LOCAL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "openapi.json")

USER = os.environ.get("SAFERPLACES_USER")
TOKEN = os.environ.get("SAFERPLACES_TOKEN")
if not USER or not TOKEN:
    # Non solleviamo un'eccezione qui: alcuni ambienti di deploy (es.
    # FastMCP Cloud) importano il modulo in fase di build, prima che le
    # variabili d'ambiente/secret siano disponibili. La verifica vera e
    # propria avviene nell'hook inject_credentials, al momento della
    # richiesta effettiva.
    print(
        "ATTENZIONE: SAFERPLACES_USER e/o SAFERPLACES_TOKEN non impostate. "
        "Le richieste verso l'API falliranno finché non le configuri.",
    )

# Nomi dei campi del body in cui l'API si aspetta le credenziali.
# ADATTA se la documentazione usa nomi diversi (es. "username", "token_user").
USER_FIELD = "user"
TOKEN_FIELD = "token"

# Se le credenziali vanno annidate dentro "inputs" (tipico di OGC API
# Processes, dove il body è {"inputs": {...}}), lascia True.
CREDENTIALS_INSIDE_INPUTS = True


async def inject_credentials(request: httpx.Request) -> None:
    """Hook httpx: inietta user e token nel body JSON di ogni POST/PUT/PATCH."""
    if request.method not in ("POST", "PUT", "PATCH"):
        return
    if not USER or not TOKEN:
        raise RuntimeError(
            "Imposta le variabili d'ambiente SAFERPLACES_USER e SAFERPLACES_TOKEN "
            "prima di effettuare richieste."
        )
    try:
        body = json.loads(request.content.decode("utf-8")) if request.content else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return  # body non-JSON: non tocchiamo nulla

    target = body
    if CREDENTIALS_INSIDE_INPUTS:
        body.setdefault("inputs", {})
        target = body["inputs"]

    target.setdefault(USER_FIELD, USER)
    target.setdefault(TOKEN_FIELD, TOKEN)

    new_content = json.dumps(body).encode("utf-8")
    request._content = new_content
    request.headers["Content-Length"] = str(len(new_content))
    request.headers["Content-Type"] = "application/json"


def build_server() -> FastMCP:
    # Client HTTP con l'hook di autenticazione e timeout generosi
    # (le simulazioni possono richiedere tempo).
    client = httpx.AsyncClient(
        base_url=BASE_URL,
        timeout=httpx.Timeout(300.0, connect=15.0),
        event_hooks={"request": [inject_credentials]},
    )

    # Prova prima la copia locale (nessuna dipendenza dalla rete in fase di
    # build/inspect), poi scarica dal server se non presente o non valida.
    spec = None
    if os.path.exists(OPENAPI_LOCAL_PATH):
        try:
            with open(OPENAPI_LOCAL_PATH, "r", encoding="utf-8") as f:
                spec = json.load(f)
        except (OSError, json.JSONDecodeError):
            spec = None
    if spec is None:
        spec = httpx.get(OPENAPI_URL, timeout=30.0).json()

    mcp = FastMCP.from_openapi(
        openapi_spec=spec,
        client=client,
        name="SaferPlaces",
    )
    return mcp


# Istanza a livello di modulo: necessaria per i deploy cloud (es. FastMCP
# Cloud) che importano l'oggetto `mcp` direttamente da questo file.
mcp = build_server()


if __name__ == "__main__":
    if os.environ.get("MCP_TRANSPORT", "stdio") == "http":
        # Modalità remota: server HTTP raggiungibile via URL, da usare
        # per il deploy su cloud e il collegamento come connettore in Claude.ai.
        mcp.run(
            transport="http",
            host="0.0.0.0",
            port=int(os.environ.get("PORT", 8000)),
        )
    else:
        # Modalità locale: trasporto stdio, adatto a Claude Desktop / Claude Code.
        mcp.run()
