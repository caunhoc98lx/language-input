import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from main import app  # đổi lại nếu file app tên khác


def application(environ, start_response):
    try:
        # Đọc body request (cần cho POST/PUT/PATCH)
        try:
            content_length = int(environ.get("CONTENT_LENGTH") or 0)
        except ValueError:
            content_length = 0
        body = environ["wsgi.input"].read(content_length) if content_length > 0 else b""

        headers = []
        for key, value in environ.items():
            if key.startswith("HTTP_"):
                header_name = key[5:].replace("_", "-").lower().encode()
                headers.append((header_name, value.encode("latin1")))
            elif key == "CONTENT_TYPE":
                headers.append((b"content-type", value.encode("latin1")))
            elif key == "CONTENT_LENGTH":
                headers.append((b"content-length", value.encode("latin1")))

        scheme = "https" if environ.get("HTTPS") == "on" or environ.get("wsgi.url_scheme") == "https" else "http"

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": environ.get("REQUEST_METHOD", "GET"),
            "scheme": scheme,
            "path": environ.get("PATH_INFO", "/"),
            "raw_path": environ.get("PATH_INFO", "/").encode(),
            "query_string": environ.get("QUERY_STRING", "").encode(),
            "headers": headers,
            "server": (environ.get("SERVER_NAME", "localhost"), int(environ.get("SERVER_PORT") or 80)),
            "client": (environ.get("REMOTE_ADDR", "0.0.0.0"), 0),
        }

        messages = []
        body_sent = False

        async def receive():
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}

        async def send(message):
            messages.append(message)

        async def call_asgi():
            await app(scope, receive, send)

        asyncio.run(call_asgi())

        status_code = 500
        resp_headers = [("Content-Type", "text/plain")]
        response_body = b""
        for m in messages:
            if m["type"] == "http.response.start":
                status_code = m["status"]
                resp_headers = [(k.decode("latin1"), v.decode("latin1")) for k, v in m.get("headers", [])]
            elif m["type"] == "http.response.body":
                response_body += m.get("body", b"")

        status_line = f"{status_code} {STATUS_TEXT.get(status_code, '')}".strip()
        start_response(status_line, resp_headers)
        return [response_body]

    except Exception as e:
        import traceback
        traceback.print_exc(file=sys.stderr)
        start_response("500 Internal Server Error", [("Content-Type", "text/plain")])
        return [f"Internal Server Error: {e}".encode()]


STATUS_TEXT = {
    200: "OK", 201: "Created", 204: "No Content",
    301: "Moved Permanently", 302: "Found",
    400: "Bad Request", 401: "Unauthorized", 403: "Forbidden",
    404: "Not Found", 405: "Method Not Allowed",
    422: "Unprocessable Entity", 500: "Internal Server Error",
}