# Bug: tutti i tool `execute*Job` falliscono con `'str' object has no attribute 'setdefault'`

## Sintomo

Ogni chiamata a un tool MCP generato per un endpoint `POST /processes/{id}/execution`
(es. `executeDigital_twin_processJob`, `executeSafer_rain_processJob`, ecc.) fallisce
sempre con lo stesso errore, indipendentemente dal processo e dagli `inputs` passati:

```
Error calling tool 'executeDigital_twin_processJob': 'str' object has no attribute 'setdefault'
```

## Riproduzione

Testato tramite il connettore MCP saferplaces in Claude Code:

1. `executeDigital_twin_processJob(inputs={"bbox": [12.53, 44.02, 12.60, 44.08], ...})` → errore.
2. Rimuovendo progressivamente i campi (`landuse_dataset`, `dem_dataset`, `building_dataset`,
   `project`, `workspace`, `overwrite`) l'errore resta identico.
3. Anche con `inputs={}` (body minimo possibile) l'errore è lo stesso.
4. Provato su un processo completamente diverso, `executeSafer_rain_processJob(inputs={})`
   → stesso identico errore.

Questo esclude che la causa sia nei valori dei parametri passati (es. nomi dataset non
validi): il bug si manifesta prima ancora che il body raggiunga l'API saferplaces.

## Dove si genera l'errore

Il messaggio corrisponde esattamente al pattern di codice in
[saferplaces_mcp.py:73-78](saferplaces_mcp.py#L73-L78), dentro l'hook httpx
`inject_credentials` che inietta `user`/`token` in ogni richiesta POST:

```python
target = body
if CREDENTIALS_INSIDE_INPUTS:
    body.setdefault("inputs", {})      # riga 74
    target = body["inputs"]

target.setdefault(USER_FIELD, USER)    # riga 77
target.setdefault(TOKEN_FIELD, TOKEN)
```

`body = json.loads(request.content.decode("utf-8"))` (riga 68). Il codice assume che
il body JSON della richiesta sia sempre un **oggetto** (`dict`). L'eccezione dice che
invece è una **stringa** (`str`): `json.loads` ha deserializzato una stringa JSON, non
un oggetto — cioè il body HTTP effettivo non è `{"inputs": {...}}` ma un valore
JSON-stringa (es. contenuto letteralmente come `"{\"inputs\": {}}"`, doppiamente
serializzato), oppure comunque un valore scalare.

## Ipotesi sulla causa radice

Lo schema OpenAPI per il campo `inputs` di ogni endpoint `.../execution` (vedi
`openapi.json`) è definito con nesting `oneOf` molto profondo per gestire i tipi
eterogenei dei parametri OGC API Processes (stringa, numero, bbox-object, `qualifiedInputValue`,
link, array...). È plausibile che FastMCP (`FastMCP.from_openapi`), nel tradurre questo
schema molto annidato in un parametro di tool, non riesca a determinarne correttamente
la forma come oggetto e finisca per serializzare l'intero valore di `inputs` come
stringa JSON nel body della richiesta HTTP, invece che come oggetto JSON annidato.
Questo spiegherebbe perché il bug è identico su processi diversi e indipendente dal
contenuto di `inputs` (compreso il caso `inputs={}`).

Va verificato con log/debug diretti su come FastMCP costruisce `request.content` per
queste operazioni (i.e. stampare `request.content` prima dell'hook, o testare
`FastMCP.from_openapi` isolatamente con lo schema di un solo endpoint `execution`).

## Impatto

Nessun processo è eseguibile tramite il connettore MCP: tutti i tool `execute*Job`
sono attualmente non funzionanti. I tool di sola lettura (`getLandingPage`,
`getProcesses`, `getCollections`, `describe*Process`, ecc.) funzionano correttamente,
quindi il problema è specifico alla generazione/serializzazione del body per le
operazioni `POST .../execution`.

## Azioni consigliate

1. **Fix difensivo immediato** in `inject_credentials` per evitare il crash silenzioso
   e ottenere un errore diagnostico più utile (es. body grezzo loggato) invece del
   solo `AttributeError`:

   ```python
   if not isinstance(body, dict):
       raise RuntimeError(
           f"Body della richiesta non è un oggetto JSON come atteso "
           f"(tipo={type(body).__name__}, contenuto={body!r})"
       )
   ```

2. **Diagnosi root cause**: loggare/ispezionare `request.content` grezzo (prima del
   parsing) per una chiamata reale, per confermare se è effettivamente una stringa
   JSON doppiamente serializzata.

3. Se confermato un problema di FastMCP con schemi `oneOf` molto annidati, valutare:
   - semplificare lo schema `inputs` nello `openapi.json` bundlato per l'operazione
     `execution` (meno `oneOf` annidati, più permissivo/generico), oppure
   - aggiornare/pinnare una versione di `fastmcp` con questo problema risolto, oppure
   - bypassare `FastMCP.from_openapi` per gli endpoint `execution` e definire questi
     tool manualmente con uno schema di input più semplice.

## Ambiente

- Repo: `stebubu/saferplaces_mcp` (branch `main`, commit `cd1f60f`)
- File coinvolto: [saferplaces_mcp.py](saferplaces_mcp.py)
- Spec OpenAPI bundlata: `openapi.json` (generata da `tools/bundle_openapi.py`)
