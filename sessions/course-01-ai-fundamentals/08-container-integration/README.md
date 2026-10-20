# Session 8 — Container Integration

Commands run from the repository root. Requirements: Docker Desktop running
and `OPENAI_API_KEY` configured in `.env`. AI requests use the configured account.

## Setup

```powershell
uv sync
```

## Exercise 1

```powershell
uv run python sessions/08-container-integration/starter/01_runtime_preflight.py
```

## Exercise 2

```powershell
uv run python sessions/08-container-integration/starter/02_initialization_comparison.py
```

Individual modes:

```powershell
uv run python sessions/08-container-integration/starter/02_initialization_comparison.py --mode repeated
uv run python sessions/08-container-integration/starter/02_initialization_comparison.py --mode reused
```

## Start the application

```powershell
docker compose -f sessions/08-container-integration/starter/compose.yaml up --build -d
```

UI: `http://localhost:8501`. API: `http://localhost:8000`.

API status:

```powershell
Invoke-RestMethod http://localhost:8000/health
```

## Exercise 3

Alternative configuration:

```powershell
docker compose -f sessions/08-container-integration/starter/compose.yaml -f sessions/08-container-integration/starter/compose.integration-error.yaml up --build -d
```

Once the API and UI are running:

```powershell
uv run python sessions/08-container-integration/starter/03_integration_check.py
```

## Exercise 4

`SESSION_ID` is the ID displayed in the UI sidebar. The `before` command
requires a session with existing messages.

```powershell
uv run python sessions/08-container-integration/starter/04_restart_state.py before --session-id "SESSION_ID"
uv run python sessions/08-container-integration/starter/04_restart_state.py after --session-id "SESSION_ID"
```

## Restart the API

```powershell
docker compose -f sessions/08-container-integration/starter/compose.yaml restart api
```

## API logs

```powershell
docker compose -f sessions/08-container-integration/starter/compose.yaml logs -f api
```

## Stop the application

```powershell
docker compose -f sessions/08-container-integration/starter/compose.yaml stop
```
