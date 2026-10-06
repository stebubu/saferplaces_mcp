"""
Server MCP per SaferPlaces — processi di simulazione (api.saferplaces.co)
=========================================================================

Espone come tool MCP i processi SaferPlaces (OGC API Processes):
descrizione, esecuzione delle simulazioni (sincrona o asincrona),
stato dei job e risultati. Le credenziali (user + token) vengono
iniettate nel body di ogni richiesta di esecuzione: non passano mai
per la chat.

Processi supportati (descrizioni lette live dal server, f=json|jsonld):
    https://api.saferplaces.co/processes/untrim-process
    https://api.saferplaces.co/processes/digital-twin-process
    https://api.saferplaces.co/processes/terra-twin-process

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
import asyncio
import httpx
from typing import Any, Literal
from fastmcp import FastMCP

BASE_URL = "https://api.saferplaces.co"

# Processi esposti dal server. Per aggiungerne uno basta inserire qui
# il suo id (come appare in /processes) e aggiornare il Literal sotto.
PROCESS_IDS = [
    "untrim-process",
    "digital-twin-process",
    "terra-twin-process",
    "safer-coast-process",
]
ProcessId = Literal[
    "untrim-process",
    "digital-twin-process",
    "terra-twin-process",
    "safer-coast-process",
]

USER = os.environ.get("SAFERPLACES_USER")
TOKEN = os.environ.get("SAFERPLACES_TOKEN")
if not USER or not TOKEN:
    raise RuntimeError(
        "Imposta le variabili d'ambiente SAFERPLACES_USER e SAFERPLACES_TOKEN "
        "prima di avviare il server."
    )

# Nomi dei campi delle credenziali nel body (verificati sulla descrizione
# live dei processi: vanno dentro "inputs").
USER_FIELD = "user"
TOKEN_FIELD = "token"
CREDENTIALS_INSIDE_INPUTS = True


async def inject_credentials(request: httpx.Request) -> None:
    """Hook httpx: inietta user e token nel body JSON di ogni POST/PUT/PATCH."""
    if request.method not in ("POST", "PUT", "PATCH"):
        return
    try:
        body = json.loads(request.content.decode("utf-8")) if request.content else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return  # body non-JSON: non tocchiamo nulla

    if not isinstance(body, dict):
        raise RuntimeError(
            f"inject_credentials: body della richiesta non è un oggetto JSON "
            f"(tipo={type(body).__name__}, contenuto={body!r})"
        )

    target = body
    if CREDENTIALS_INSIDE_INPUTS:
        if "inputs" not in body:
            body["inputs"] = {}
        elif not isinstance(body["inputs"], dict):
            raise RuntimeError(
                f"inject_credentials: 'inputs' non è un oggetto JSON "
                f"(tipo={type(body['inputs']).__name__}, contenuto={body['inputs']!r})"
            )
        target = body["inputs"]

    target.setdefault(USER_FIELD, USER)
    target.setdefault(TOKEN_FIELD, TOKEN)

    new_content = json.dumps(body).encode("utf-8")
    request._content = new_content
    request.stream = httpx.ByteStream(new_content)
    request.headers["Content-Length"] = str(len(new_content))
    request.headers["Content-Type"] = "application/json"


client = httpx.AsyncClient(
    base_url=BASE_URL,
    timeout=httpx.Timeout(300.0, connect=15.0),
    event_hooks={"request": [inject_credentials]},
)

mcp = FastMCP(name="SaferPlaces")


@mcp.tool
async def list_processes() -> dict:
    """Elenco dei processi di simulazione disponibili sull'API SaferPlaces,
    con id e descrizione sintetica."""
    r = await client.get("/processes", params={"f": "json"})
    r.raise_for_status()
    return r.json()


@mcp.tool
async def process_describe(
    process_id: ProcessId,
    format: Literal["json", "jsonld"] = "json",
) -> dict:
    """Descrizione completa di un processo: titolo, input attesi (con tipi,
    default e obbligatorietà) e output prodotti. Chiamalo PRIMA di eseguire
    una simulazione per conoscere i parametri richiesti.
    `format`: "json" (default) oppure "jsonld" (versione JSON-LD)."""
    r = await client.get(f"/processes/{process_id}", params={"f": format})
    r.raise_for_status()
    return r.json()


@mcp.tool
async def process_execute(
    process_id: ProcessId,
    params: dict[str, Any],
    async_execution: bool = True,
) -> dict:
    """Lancia un processo SaferPlaces. `params` è il dizionario dei parametri
    del processo (vedi process_describe): NON includere user e token, li
    aggiunge il server. Con async_execution=True (default) la risposta
    contiene l'id del job da monitorare con job_status; con False attende e
    restituisce direttamente il risultato (solo per esecuzioni brevi)."""
    headers = {"Prefer": "respond-async"} if async_execution else {}
    try:
        r = await client.post(
            f"/processes/{process_id}/execution",
            json={"inputs": params},
            headers=headers,
        )
    except Exception as exc:
        raise RuntimeError(
            f"process_execute({process_id!r}) fallita: tipo(params)={type(params).__name__}, "
            f"chiavi={list(params.keys()) if isinstance(params, dict) else params!r} — "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    r.raise_for_status()
    raw = r.json() if r.content else None
    out: dict = raw if isinstance(raw, dict) else {}
    if raw is not None and not isinstance(raw, dict):
        out["raw_response"] = raw
    location = r.headers.get("Location")
    if location:
        out.setdefault("job_location", location)
    return out


@mcp.tool
async def job_status(job_id: str) -> dict:
    """Stato di un job di simulazione (accepted / running / successful /
    failed) con eventuale avanzamento."""
    r = await client.get(f"/jobs/{job_id}", params={"f": "json"})
    r.raise_for_status()
    return r.json()


@mcp.tool
async def job_results(job_id: str) -> dict:
    """Risultati di un job completato (output della simulazione, URI S3
    dei file prodotti)."""
    r = await client.get(f"/jobs/{job_id}/results", params={"f": "json"})
    r.raise_for_status()
    return r.json()


@mcp.tool
async def job_cancel(job_id: str) -> dict:
    """Annulla/ferma un job in corso (dismiss, standard OGC API Processes)."""
    r = await client.delete(f"/jobs/{job_id}", params={"f": "json"})
    r.raise_for_status()
    return r.json() if r.content else {"status": "dismissed", "job_id": job_id}


@mcp.tool
async def list_jobs(limit: int = 10) -> dict:
    """Elenco dei job recenti sull'API, con stato e id."""
    r = await client.get("/jobs", params={"limit": limit, "f": "json"})
    r.raise_for_status()
    return r.json()


@mcp.tool
async def process_run_and_wait(
    process_id: ProcessId,
    params: dict[str, Any],
    poll_seconds: int = 15,
    timeout_seconds: int = 1800,
) -> dict:
    """Lancia un processo e attende il completamento, facendo polling dello
    stato ogni `poll_seconds`. Restituisce i risultati del job (o lo stato
    di errore). Usa process_execute + job_status se preferisci gestire
    l'attesa manualmente."""
    started = await process_execute.fn(process_id, params, async_execution=True)
    job_id = started.get("jobID") or started.get("job_id") or started.get("id")
    if not job_id and started.get("job_location"):
        job_id = started["job_location"].rstrip("/").split("/")[-1]
    if not job_id:
        return {"error": "Nessun job id nella risposta di esecuzione", "response": started}

    waited = 0
    while waited < timeout_seconds:
        status = await job_status.fn(job_id)
        state = str(status.get("status", "")).lower()
        if state in ("successful", "succeeded", "failed", "dismissed"):
            if state.startswith("succ"):
                return await job_results.fn(job_id)
            return {"error": f"Job terminato con stato '{state}'", "status": status}
        await asyncio.sleep(poll_seconds)
        waited += poll_seconds

    return {"error": f"Timeout dopo {timeout_seconds}s", "job_id": job_id}


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
