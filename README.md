# Dida365-API

滴答清单的 API (根据 Web 端接口提取)

An API based on Dida365 Web.

由于官方提供的 API 功能较弱，自行封装了一个。

I made this due to the lack of features of official API.

---

如有侵权，即刻撤下。

If it violate Dida365's copyrights, please contact me. I'd remove this repo ASAP.

## Local OpenAPI Wrapper

This repository also includes a small Python wrapper for the Dida365 OpenAPI.

### Run with Python

```bash
python3 api.py
```

Open `http://localhost:8080` once to authorize. After authorization, the access
token is saved to `data/token.json`.

### Run with Docker

Create your local environment file:

```bash
cp .env.example .env
```

Edit `.env`, then start the service:

```bash
docker compose up --build
```

Open `http://localhost:8080` once to authorize. The token is persisted through
the `./data:/app/data` volume.

### Call the Local API

When `DIDA_WRAPPER_API_KEY` is set, send it as `X-API-Key`:

```bash
curl http://localhost:8080/projects \
  -H "X-API-Key: change-this-local-api-key"
```

Create a task:

```bash
curl -X POST http://localhost:8080/tasks \
  -H "Content-Type: application/json" \
  -H "X-API-Key: change-this-local-api-key" \
  -d '{"title":"Test task","content":"Created from local wrapper","timeZone":"Asia/Shanghai"}'
```

List available wrapper routes:

```bash
curl http://localhost:8080/routes \
  -H "X-API-Key: change-this-local-api-key"
```

### Google Calendar Subscription

The wrapper can expose open Dida365 tasks as an iCalendar feed. Set a separate
feed token in `.env`:

```bash
DIDA_CALENDAR_FEED_TOKEN=change-this-calendar-feed-token
DIDA_CALENDAR_NAME=Dida365 Tasks
```

Then subscribe to this URL in Google Calendar:

```text
http://localhost:8080/calendar.ics?token=change-this-calendar-feed-token
```

For Google Calendar to refresh it automatically, the URL must be reachable by
Google. That means `localhost` is only useful for local testing; for real
subscription sync, deploy the Docker service to a server and use an HTTPS URL:

```text
https://your-domain.example/calendar.ics?token=change-this-calendar-feed-token
```

Optional filters:

```text
https://your-domain.example/calendar.ics?token=...&projectIds=project1,project2&tags=work
```

### MCP Server

The wrapper can also be exposed to MCP clients through `mcp_server.py`. The MCP
server is a local stdio process that calls this HTTP wrapper, so the wrapper can
run locally in Docker or remotely on a server.

Example MCP configuration:

```json
{
  "mcpServers": {
    "dida365": {
      "command": "python3",
      "args": ["/absolute/path/to/Dida365-API/mcp_server.py"],
      "env": {
        "DIDA_WRAPPER_BASE_URL": "https://your-domain.example",
        "DIDA_WRAPPER_API_KEY": "your-wrapper-api-key",
        "DIDA_CALENDAR_FEED_TOKEN": "your-calendar-feed-token"
      }
    }
  }
}
```

Local Docker example:

```json
{
  "mcpServers": {
    "dida365": {
      "command": "python3",
      "args": ["/absolute/path/to/Dida365-API/mcp_server.py"],
      "env": {
        "DIDA_WRAPPER_BASE_URL": "http://127.0.0.1:8080",
        "DIDA_WRAPPER_API_KEY": "change-this-local-api-key",
        "DIDA_CALENDAR_FEED_TOKEN": "change-this-calendar-feed-token"
      }
    }
  }
}
```

MCP tools:

- `dida_health`
- `dida_list_projects`
- `dida_create_task`
- `dida_filter_tasks`
- `dida_get_task`
- `dida_update_task`
- `dida_complete_task`
- `dida_delete_task`
- `dida_calendar_feed_url`
