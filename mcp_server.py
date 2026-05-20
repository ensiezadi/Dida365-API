import json
import os
import sys
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


BASE_URL = os.getenv("DIDA_WRAPPER_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
API_KEY = os.getenv("DIDA_WRAPPER_API_KEY", "")
CALENDAR_FEED_TOKEN = os.getenv("DIDA_CALENDAR_FEED_TOKEN", "")


TOOLS = [
    {
        "name": "dida_health",
        "description": "Check whether the Dida365 wrapper is reachable and authorized.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "dida_list_projects",
        "description": "List Dida365 projects.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "dida_create_task",
        "description": "Create a Dida365 task.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "projectId": {"type": "string"},
                "content": {"type": "string"},
                "desc": {"type": "string"},
                "dueDate": {"type": "string", "description": "yyyy-MM-dd'T'HH:mm:ssZ"},
                "startDate": {"type": "string", "description": "yyyy-MM-dd'T'HH:mm:ssZ"},
                "timeZone": {"type": "string", "default": "Asia/Shanghai"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "priority": {"type": "integer", "description": "0 none, 1 low, 3 medium, 5 high"},
            },
            "required": ["title"],
        },
    },
    {
        "name": "dida_filter_tasks",
        "description": "Filter Dida365 tasks.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "projectIds": {"type": "array", "items": {"type": "string"}},
                "startDate": {"type": "string"},
                "endDate": {"type": "string"},
                "priority": {"type": "array", "items": {"type": "integer"}},
                "tag": {"type": "array", "items": {"type": "string"}},
                "status": {"type": "array", "items": {"type": "integer"}},
            },
        },
    },
    {
        "name": "dida_get_task",
        "description": "Get one Dida365 task by project ID and task ID.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "projectId": {"type": "string"},
                "taskId": {"type": "string"},
            },
            "required": ["projectId", "taskId"],
        },
    },
    {
        "name": "dida_update_task",
        "description": "Update a Dida365 task.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "projectId": {"type": "string"},
                "title": {"type": "string"},
                "content": {"type": "string"},
                "desc": {"type": "string"},
                "dueDate": {"type": "string"},
                "startDate": {"type": "string"},
                "timeZone": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "priority": {"type": "integer"},
            },
            "required": ["id", "projectId"],
        },
    },
    {
        "name": "dida_complete_task",
        "description": "Complete a Dida365 task.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "projectId": {"type": "string"},
                "taskId": {"type": "string"},
            },
            "required": ["projectId", "taskId"],
        },
    },
    {
        "name": "dida_delete_task",
        "description": "Delete a Dida365 task.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "projectId": {"type": "string"},
                "taskId": {"type": "string"},
            },
            "required": ["projectId", "taskId"],
        },
    },
    {
        "name": "dida_calendar_feed_url",
        "description": "Return the Dida365 iCalendar feed URL for Google Calendar subscription.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "projectIds": {"type": "array", "items": {"type": "string"}},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
]


def wrapper_request(method, path, payload=None):
    headers = {"Accept": "application/json"}
    if API_KEY:
        headers["X-API-Key"] = API_KEY

    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = Request(f"{BASE_URL}{path}", method=method, headers=headers, data=data)
    try:
        response = urlopen(request)
    except HTTPError as exc:
        response = exc

    with response:
        body = response.read().decode("utf-8")
        if not body:
            return {"status": response.status, "body": None}
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = body
        return {"status": response.status, "body": parsed}


def text_result(value):
    return {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False, indent=2)}]}


def call_tool(name, arguments):
    args = arguments or {}

    if name == "dida_health":
        return text_result(wrapper_request("GET", "/health"))
    if name == "dida_list_projects":
        return text_result(wrapper_request("GET", "/projects"))
    if name == "dida_create_task":
        return text_result(wrapper_request("POST", "/tasks", args))
    if name == "dida_filter_tasks":
        return text_result(wrapper_request("POST", "/tasks/filter", args))
    if name == "dida_get_task":
        path = f"/projects/{args['projectId']}/tasks/{args['taskId']}"
        return text_result(wrapper_request("GET", path))
    if name == "dida_update_task":
        task_id = args["id"]
        return text_result(wrapper_request("POST", f"/tasks/{task_id}", args))
    if name == "dida_complete_task":
        path = f"/projects/{args['projectId']}/tasks/{args['taskId']}/complete"
        return text_result(wrapper_request("POST", path))
    if name == "dida_delete_task":
        path = f"/projects/{args['projectId']}/tasks/{args['taskId']}"
        return text_result(wrapper_request("DELETE", path))
    if name == "dida_calendar_feed_url":
        if not CALENDAR_FEED_TOKEN:
            return text_result({"error": "DIDA_CALENDAR_FEED_TOKEN is not set"})
        query = {"token": CALENDAR_FEED_TOKEN}
        if args.get("projectIds"):
            query["projectIds"] = ",".join(args["projectIds"])
        if args.get("tags"):
            query["tags"] = ",".join(args["tags"])
        return text_result({"url": f"{BASE_URL}/calendar.ics?{urlencode(query)}"})

    raise ValueError(f"unknown tool: {name}")


def handle(request):
    method = request.get("method")
    request_id = request.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "dida365-wrapper-mcp", "version": "0.1.0"},
            },
        }
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = request.get("params", {})
        result = call_tool(params.get("name"), params.get("arguments", {}))
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -32601, "message": f"method not found: {method}"},
    }


def main():
    for line in sys.stdin:
        request_id = None
        try:
            request = json.loads(line)
            request_id = request.get("id")
            response = handle(request)
        except Exception as exc:
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32603, "message": str(exc)},
            }
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
