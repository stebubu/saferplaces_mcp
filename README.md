# SaferPlaces MCP Server

Server MCP che espone le REST API di [SaferPlaces](https://api.saferplaces.co) come tool utilizzabili da Claude, per lanciare e monitorare simulazioni direttamente dalla chat.

I tool vengono generati automaticamente all'avvio a partire dalla specifica OpenAPI (`https://api.saferplaces.co/openapi?f=json`). Le credenziali (utente e token) vengono iniettate dal server nel body di ogni richiesta di scrittura: non passano mai per la chat e Claude non le vede.

## Struttura del repo

```
saferplaces_mcp.py    # il server MCP
requirements.txt      # dipendenze Python (fastmcp, httpx)
README.md
```

## Configurazione

Il server richiede due variabili d'ambiente:

| Variabile           | Descrizione                     |
|---------------------|---------------------------------|
| `SAFERPLACES_USER`  | Nome utente SaferPlaces         |
| `SAFERPLACES_TOKEN` | Token associato all'utente      |

In cima a `saferplaces_mcp.py` ci sono tre costanti da verificare rispetto alla documentazione delle API:

- `USER_FIELD` e `TOKEN_FIELD`: i nomi esatti dei campi del body in cui l'API si aspetta le credenziali (default: `user` e `token`).
- `CREDENTIALS_INSIDE_INPUTS`: `True` se le credenziali vanno annidate dentro l'oggetto `inputs` del body (tipico delle OGC API Processes), `False` se vanno al livello principale.

## Uso locale (Claude Code / Claude Desktop)

Richiede Python 3.10+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export SAFERPLACES_USER="tuo-utente"
export SAFERPLACES_TOKEN="tuo-token"

# test rapido: deve avviarsi senza errori (Ctrl+C per fermarlo)
python saferplaces_mcp.py
```

Collegamento a Claude Code (usa i percorsi assoluti):

```bash
claude mcp add saferplaces \
  -e SAFERPLACES_USER=tuo-utente \
  -e SAFERPLACES_TOKEN=tuo-token \
  -- /percorso/assoluto/.venv/bin/python /percorso/assoluto/saferplaces_mcp.py
```

Verifica con `/mcp` dentro Claude Code: il server `saferplaces` deve comparire tra quelli connessi.

## Deploy remoto (connettore per Claude.ai)

In modalità remota il server gira su un hosting raggiungibile via HTTPS e si collega a Claude.ai da **Impostazioni → Connettori → Aggiungi connettore personalizzato**, incollando l'URL. Funziona da browser e da mobile, senza nulla in esecuzione in locale.

Il trasporto HTTP si attiva con la variabile d'ambiente `MCP_TRANSPORT=http` (la porta si imposta con `PORT`, default 8000).

### Opzione A — FastMCP Cloud

1. Carica questo repo su GitHub.
2. Su [fastmcp.cloud](https://fastmcp.cloud) collega il repo: la piattaforma rileva l'oggetto `mcp` in `saferplaces_mcp.py` e lo deploya.
3. Imposta `SAFERPLACES_USER` e `SAFERPLACES_TOKEN` tra le variabili d'ambiente del progetto.
4. Copia l'URL HTTPS generato e incollalo nei connettori di Claude.ai.

### Opzione B — hosting generico (Cloud Run, Render, Railway, ...)

Comando di avvio:

```bash
MCP_TRANSPORT=http python saferplaces_mcp.py
```

Imposta `SAFERPLACES_USER`, `SAFERPLACES_TOKEN` e (se richiesto dalla piattaforma) `PORT` tra le variabili d'ambiente del servizio.

## Sicurezza

⚠️ Un server remoto con le credenziali configurate permette a **chiunque ne conosca l'URL** di lanciare simulazioni con il tuo account e consumare la tua quota. Prima di esporlo su internet, proteggilo con l'autenticazione (FastMCP supporta bearer token e OAuth — vedi la documentazione di FastMCP, sezione *Auth*). Non committare mai le credenziali nel repo.

## Risoluzione problemi

- **`ModuleNotFoundError: httpx` / `fastmcp`** → le dipendenze non sono installate nell'ambiente Python attivo: `pip install -r requirements.txt`.
- **Errore all'avvio su variabili d'ambiente** → `SAFERPLACES_USER` o `SAFERPLACES_TOKEN` non impostate.
- **Errore di autenticazione dalle API** → controlla `USER_FIELD`, `TOKEN_FIELD` e `CREDENTIALS_INSIDE_INPUTS` in cima a `saferplaces_mcp.py`: devono rispecchiare il body di una chiamata funzionante fatta a mano.
- **Timeout su simulazioni lunghe** → il timeout del client è 300 s, alzalo in `build_server()` se necessario.
