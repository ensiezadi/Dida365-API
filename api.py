import base64
from datetime import datetime, timedelta, timezone
import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen


CLIENT_ID = os.getenv("DIDA_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("DIDA_CLIENT_SECRET", "")
REDIRECT_URI = os.getenv("DIDA_REDIRECT_URI", "http://localhost:8080/callback")
API_KEY = os.getenv("DIDA_WRAPPER_API_KEY", "")
CALENDAR_FEED_TOKEN = os.getenv("DIDA_CALENDAR_FEED_TOKEN", "")
CALENDAR_NAME = os.getenv("DIDA_CALENDAR_NAME", "Dida365 Tasks")
DEFAULT_TIME_ZONE = os.getenv("DIDA_DEFAULT_TIME_ZONE", "Asia/Shanghai")
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8080"))
TOKEN_FILE = Path(os.getenv("DIDA_TOKEN_FILE", "data/token.json"))
OPENAPI_BASE_URL = "https://api.dida365.com/open/v1"

TOKEN = os.getenv("DIDA_ACCESS_TOKEN", "")


def load_token():
    if TOKEN:
        return TOKEN
    if not TOKEN_FILE.exists():
        return ""
    try:
        data = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return data.get("access_token", "")


def save_token(access_token, token_response):
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(token_response)
    payload["access_token"] = access_token
    TOKEN_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def request_json(url, method="GET", headers=None, data=None):
    request = Request(url, method=method, headers=headers or {}, data=data)
    try:
        response = urlopen(request)
    except HTTPError as exc:
        response = exc

    with response:
        body = response.read().decode("utf-8")
        if not body:
            return response.status, None
        try:
            return response.status, json.loads(body)
        except json.JSONDecodeError:
            return response.status, {"raw": body}


def parse_dida_datetime(value):
    if not value:
        return None
    normalized = value
    if len(value) >= 5 and value[-5] in {"+", "-"} and value[-3] != ":":
        normalized = f"{value[:-2]}:{value[-2:]}"
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def ics_escape(value):
    return (
        str(value or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def ics_fold(line):
    encoded = line.encode("utf-8")
    if len(encoded) <= 75:
        return line

    parts = []
    current = ""
    for char in line:
        prefix = " " if parts else ""
        candidate = f"{prefix}{current}{char}"
        if len(candidate.encode("utf-8")) > 75:
            parts.append(current)
            current = char
        else:
            current = f"{current}{char}"
    if current:
        parts.append((" " if parts else "") + current)
    return "\r\n".join(parts)


def ics_datetime(value):
    parsed = parse_dida_datetime(value)
    if not parsed:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def ics_date(value):
    parsed = parse_dida_datetime(value)
    if not parsed:
        return None
    return parsed.strftime("%Y%m%d")


def task_to_ics_event(task, dtstamp):
    start = task.get("startDate") or task.get("dueDate")
    due = task.get("dueDate") or task.get("startDate")
    if not start and not due:
        return []

    uid = task.get("id") or f"{task.get('projectId', 'project')}-{task.get('title', 'task')}"
    title = task.get("title") or "Untitled Dida task"
    description_parts = [
        task.get("content"),
        task.get("desc"),
        f"Project: {task.get('projectId')}" if task.get("projectId") else None,
        f"Tags: {', '.join(task.get('tags', []))}" if task.get("tags") else None,
    ]
    description = "\n".join(part for part in description_parts if part)

    lines = [
        "BEGIN:VEVENT",
        f"UID:{ics_escape(uid)}@dida365",
        f"DTSTAMP:{dtstamp}",
        f"SUMMARY:{ics_escape(title)}",
    ]
    if description:
        lines.append(f"DESCRIPTION:{ics_escape(description)}")

    if task.get("isAllDay"):
        start_date = ics_date(start)
        due_date = ics_date(due)
        if start_date:
            lines.append(f"DTSTART;VALUE=DATE:{start_date}")
        if due_date:
            parsed_due = parse_dida_datetime(due)
            if parsed_due:
                lines.append(f"DTEND;VALUE=DATE:{(parsed_due + timedelta(days=1)).strftime('%Y%m%d')}")
    else:
        start_date_time = ics_datetime(start)
        due_date_time = ics_datetime(due)
        if start_date_time:
            lines.append(f"DTSTART:{start_date_time}")
        if due_date_time and due_date_time != start_date_time:
            lines.append(f"DTEND:{due_date_time}")
        elif start_date_time:
            lines.append("DURATION:PT30M")

    priority = task.get("priority")
    if priority is not None:
        lines.append(f"PRIORITY:{priority}")
    lines.extend(["STATUS:CONFIRMED", "END:VEVENT"])
    return lines


class DidaHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")

    def do_DELETE(self):
        self.route("DELETE")

    def route(self, method):
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        segments = [segment for segment in path.strip("/").split("/") if segment]

        if method == "GET" and path == "/health":
            self.send_json(HTTPStatus.OK, {"ok": True, "authorized": bool(TOKEN)})
            return

        if method == "GET" and path == "/":
            self.redirect_to_authorize()
            return

        if method == "GET" and path == "/callback":
            self.handle_callback(parsed_url.query)
            return

        if method == "GET" and path == "/calendar.ics":
            self.handle_calendar_feed(parsed_url.query)
            return

        if not self.check_api_key():
            return

        if method == "GET" and path == "/routes":
            self.send_json(HTTPStatus.OK, self.route_help())
            return

        if method == "GET" and path == "/create-task":
            self.create_sample_task(parsed_url.query)
            return

        if segments[:2] == ["open", "v1"] and len(segments) > 2:
            self.proxy_openapi(method, "/" + "/".join(segments[2:]), parsed_url.query)
            return

        openapi_path = self.map_local_route(method, segments)
        if openapi_path:
            self.proxy_openapi(method, openapi_path, parsed_url.query)
            return

        self.send_json(HTTPStatus.NOT_FOUND, {"error": "not found", "routes": "/routes"})

    def check_api_key(self):
        if not API_KEY:
            return True
        if self.headers.get("X-API-Key") == API_KEY:
            return True
        self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "invalid api key"})
        return False

    def check_calendar_feed_token(self, query):
        if not CALENDAR_FEED_TOKEN:
            self.send_json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {"error": "set DIDA_CALENDAR_FEED_TOKEN before exposing /calendar.ics"},
            )
            return False
        token = parse_qs(query).get("token", [""])[0]
        if token == CALENDAR_FEED_TOKEN:
            return True
        self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "invalid calendar feed token"})
        return False

    def map_local_route(self, method, segments):
        if method == "GET":
            if segments == ["projects"]:
                return "/project"
            if len(segments) == 2 and segments[0] == "projects":
                return f"/project/{segments[1]}"
            if len(segments) == 3 and segments[0] == "projects" and segments[2] == "data":
                return f"/project/{segments[1]}/data"
            if len(segments) == 4 and segments[0] == "projects" and segments[2] == "tasks":
                return f"/project/{segments[1]}/task/{segments[3]}"
            if segments == ["focus"]:
                return "/focus"
            if len(segments) == 2 and segments[0] == "focus":
                return f"/focus/{segments[1]}"
            if segments == ["habits"]:
                return "/habit"
            if len(segments) == 2 and segments[0] == "habits":
                return f"/habit/{segments[1]}"
            if segments == ["habit-checkins"]:
                return "/habit/checkins"

        if method == "POST":
            if segments == ["tasks"]:
                return "/task"
            if segments == ["tasks", "move"]:
                return "/task/move"
            if segments == ["tasks", "completed"]:
                return "/task/completed"
            if segments == ["tasks", "filter"]:
                return "/task/filter"
            if len(segments) == 2 and segments[0] == "tasks":
                return f"/task/{segments[1]}"
            if len(segments) == 5 and segments[0] == "projects" and segments[2] == "tasks" and segments[4] == "complete":
                return f"/project/{segments[1]}/task/{segments[3]}/complete"
            if segments == ["projects"]:
                return "/project"
            if len(segments) == 2 and segments[0] == "projects":
                return f"/project/{segments[1]}"
            if segments == ["habits"]:
                return "/habit"
            if len(segments) == 3 and segments[0] == "habits" and segments[2] == "checkin":
                return f"/habit/{segments[1]}/checkin"
            if len(segments) == 2 and segments[0] == "habits":
                return f"/habit/{segments[1]}"

        if method == "DELETE":
            if len(segments) == 4 and segments[0] == "projects" and segments[2] == "tasks":
                return f"/project/{segments[1]}/task/{segments[3]}"
            if len(segments) == 2 and segments[0] == "projects":
                return f"/project/{segments[1]}"
            if len(segments) == 2 and segments[0] == "focus":
                return f"/focus/{segments[1]}"

        return None

    def redirect_to_authorize(self):
        if not CLIENT_ID:
            self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "DIDA_CLIENT_ID is not set"})
            return

        query = urlencode(
            {
                "scope": "tasks:write tasks:read",
                "client_id": CLIENT_ID,
                "redirect_uri": REDIRECT_URI,
                "response_type": "code",
                "state": "state",
            }
        )
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", f"https://dida365.com/oauth/authorize?{query}")
        self.end_headers()

    def handle_callback(self, query):
        global TOKEN

        if not CLIENT_ID or not CLIENT_SECRET:
            self.send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": "DIDA_CLIENT_ID and DIDA_CLIENT_SECRET must be set"},
            )
            return

        code = parse_qs(query).get("code", [""])[0]
        if not code:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "code not found"})
            return

        form = urlencode(
            {
                "redirect_uri": REDIRECT_URI,
                "grant_type": "authorization_code",
                "scope": "tasks:write tasks:read",
                "code": code,
            }
        ).encode("utf-8")
        basic_token = base64.b64encode(
            f"{CLIENT_ID}:{CLIENT_SECRET}".encode("utf-8")
        ).decode("utf-8")

        try:
            _, token_response = request_json(
                "https://dida365.com/oauth/token",
                method="POST",
                headers={
                    "Authorization": f"Basic {basic_token}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data=form,
            )
        except Exception as exc:
            self.send_json(HTTPStatus.BAD_GATEWAY, {"error": str(exc)})
            return

        access_token = token_response.get("access_token")
        if not access_token:
            self.send_json(
                HTTPStatus.BAD_GATEWAY,
                {"error": "access_token not found in response", "response": token_response},
            )
            return

        TOKEN = access_token
        save_token(access_token, token_response)
        self.send_json(HTTPStatus.OK, {"message": "Authorization successful"})

    def proxy_openapi(self, method, openapi_path, query):
        if not TOKEN:
            self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return

        body = self.read_json_body() if method in {"POST", "DELETE"} else None
        if isinstance(body, tuple):
            status, payload = body
            self.send_json(status, payload)
            return

        url = f"{OPENAPI_BASE_URL}{openapi_path}"
        if query:
            url = f"{url}?{query}"

        headers = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        try:
            status, response = request_json(url, method=method, headers=headers, data=data)
        except Exception as exc:
            self.send_json(HTTPStatus.BAD_GATEWAY, {"error": str(exc)})
            return

        if response is None:
            self.send_empty(status)
            return
        self.send_json(status, response)

    def create_sample_task(self, query):
        params = parse_qs(query)
        task = {
            "title": params.get("title", ["New Task"])[0],
            "content": params.get("content", ["This is the content of the task."])[0],
            "desc": params.get("desc", ["This is a new task."])[0],
            "dueDate": params.get("dueDate", ["2026-05-21T00:00:00+0800"])[0],
            "timeZone": params.get("timeZone", ["Asia/Shanghai"])[0],
        }
        if "projectId" in params:
            task["projectId"] = params["projectId"][0]
        self.proxy_openapi_with_body("POST", "/task", task)

    def proxy_openapi_with_body(self, method, openapi_path, body):
        if not TOKEN:
            self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return

        try:
            status, response = request_json(
                f"{OPENAPI_BASE_URL}{openapi_path}",
                method=method,
                headers={
                    "Authorization": f"Bearer {TOKEN}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                data=json.dumps(body).encode("utf-8"),
            )
        except Exception as exc:
            self.send_json(HTTPStatus.BAD_GATEWAY, {"error": str(exc)})
            return

        if response is None:
            self.send_empty(status)
            return
        self.send_json(status, response)

    def handle_calendar_feed(self, query):
        if not self.check_calendar_feed_token(query):
            return
        if not TOKEN:
            self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return

        params = parse_qs(query)
        body = {"status": [0]}
        project_ids = params.get("projectIds", [""])[0]
        if project_ids:
            body["projectIds"] = [item.strip() for item in project_ids.split(",") if item.strip()]
        tags = params.get("tags", [""])[0]
        if tags:
            body["tag"] = [item.strip() for item in tags.split(",") if item.strip()]

        try:
            status, tasks = request_json(
                f"{OPENAPI_BASE_URL}/task/filter",
                method="POST",
                headers={
                    "Authorization": f"Bearer {TOKEN}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                data=json.dumps(body).encode("utf-8"),
            )
        except Exception as exc:
            self.send_json(HTTPStatus.BAD_GATEWAY, {"error": str(exc)})
            return

        if status >= 400:
            self.send_json(status, tasks or {"error": "failed to fetch tasks"})
            return

        if not isinstance(tasks, list):
            self.send_json(HTTPStatus.BAD_GATEWAY, {"error": "unexpected task response", "response": tasks})
            return

        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//Hermes Dida365 Wrapper//EN",
            "CALSCALE:GREGORIAN",
            "METHOD:PUBLISH",
            f"X-WR-CALNAME:{ics_escape(CALENDAR_NAME)}",
            f"X-WR-TIMEZONE:{ics_escape(DEFAULT_TIME_ZONE)}",
            "REFRESH-INTERVAL;VALUE=DURATION:PT1H",
            "X-PUBLISHED-TTL:PT1H",
        ]
        dtstamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        for task in tasks:
            lines.extend(task_to_ics_event(task, dtstamp))
        lines.append("END:VCALENDAR")

        body_bytes = ("\r\n".join(ics_fold(line) for line in lines) + "\r\n").encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/calendar; charset=utf-8")
        self.send_header("Content-Disposition", 'inline; filename="dida365.ics"')
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        self.wfile.write(body_bytes)

    def read_json_body(self):
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length == 0:
            return None

        raw_body = self.rfile.read(content_length).decode("utf-8")
        try:
            return json.loads(raw_body)
        except json.JSONDecodeError as exc:
            return HTTPStatus.BAD_REQUEST, {"error": "invalid json", "detail": str(exc)}

    def route_help(self):
        return {
            "auth": {
                "authorize": "GET /",
                "callback": "GET /callback",
                "health": "GET /health",
            },
            "calendar": "GET /calendar.ics?token={DIDA_CALENDAR_FEED_TOKEN}",
            "security": "Set DIDA_WRAPPER_API_KEY and send X-API-Key for all non-auth routes.",
            "tasks": [
                "GET /projects/{projectId}/tasks/{taskId}",
                "POST /tasks",
                "POST /tasks/{taskId}",
                "POST /projects/{projectId}/tasks/{taskId}/complete",
                "DELETE /projects/{projectId}/tasks/{taskId}",
                "POST /tasks/move",
                "POST /tasks/completed",
                "POST /tasks/filter",
            ],
            "projects": [
                "GET /projects",
                "GET /projects/{projectId}",
                "GET /projects/{projectId}/data",
                "POST /projects",
                "POST /projects/{projectId}",
                "DELETE /projects/{projectId}",
            ],
            "focus": [
                "GET /focus?from=...&to=...&type=1",
                "GET /focus/{focusId}?type=0",
                "DELETE /focus/{focusId}?type=0",
            ],
            "habits": [
                "GET /habits",
                "GET /habits/{habitId}",
                "POST /habits",
                "POST /habits/{habitId}",
                "POST /habits/{habitId}/checkin",
                "GET /habit-checkins?habitIds=...&from=20260401&to=20260407",
            ],
            "direct_proxy": "/open/v1/{official_path}",
        }

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_empty(self, status):
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()


def main():
    global TOKEN

    TOKEN = load_token()
    if not CLIENT_ID:
        print("Warning: DIDA_CLIENT_ID is not set; OAuth authorize URL will not work.")
    if not CLIENT_SECRET:
        print("Warning: DIDA_CLIENT_SECRET is not set; OAuth callback will not work.")

    query = urlencode(
        {
            "scope": "tasks:write tasks:read",
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "state": "state",
        }
    )
    server = ThreadingHTTPServer((HOST, PORT), DidaHandler)
    print(f"Listening on http://{HOST}:{PORT}")
    print(f"OAuth redirect URI: {REDIRECT_URI}")
    print(f"Token file: {TOKEN_FILE}")
    print(f"API key required: {bool(API_KEY)}")
    print(f"Route list: http://localhost:{PORT}/routes")
    print(f"Authorize URL: https://dida365.com/oauth/authorize?{query}")
    server.serve_forever()


if __name__ == "__main__":
    main()
