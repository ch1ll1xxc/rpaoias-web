"""Локальный сервер отладчика. Не предназначен для публикации в интернете."""

import argparse
import json
import secrets
import time
import webbrowser
from collections import OrderedDict
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from threading import RLock, Timer
from urllib.parse import urlsplit

from rpaoias.errors import EmulatorError
from rpaoias.web.model import EXAMPLE_NAMES, Session, source_for

STATIC = {"/": ("index.html", "text/html; charset=utf-8"),
          "/app.js": ("app.js", "text/javascript; charset=utf-8"),
          "/style.css": ("style.css", "text/css; charset=utf-8"),
          "/gravity-ui.css": ("gravity-ui.css", "text/css; charset=utf-8")}
COOKIE = "rpaoias_web"
MAX_BODY = 150_000
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; "
       "frame-ancestors 'none'; form-action 'none'")


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address=("127.0.0.1", 8080)):
        if address[0] != "127.0.0.1":
            raise ValueError("Этот сервер разрешено запускать только на 127.0.0.1")
        self.sessions = OrderedDict()
        self.sessions_lock = RLock()
        super().__init__(address, Handler)

    def get_session(self, key: str, create=False):
        with self.sessions_lock:
            now = time.monotonic()
            for old in list(self.sessions):
                if now - self.sessions[old][3] > 7200:
                    del self.sessions[old]
            if key in self.sessions:
                item = self.sessions.pop(key)
                item[3] = now
                self.sessions[key] = item
                return item
            if not create:
                return None
            while len(self.sessions) >= 16:
                self.sessions.popitem(last=False)
            sid, token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            item = [sid, token, Session(), now]
            self.sessions[sid] = item
            return item


class Handler(BaseHTTPRequestHandler):
    server_version = "RPAOIAS-local"

    def log_message(self, fmt, *args):
        # Код ассемблера и идентификаторы сеанса в лог не выводим.
        if args and len(args) >= 2 and str(args[1]).startswith("5"):
            super().log_message(fmt, *args)

    def send(self, status, payload, mime="application/json; charset=utf-8", cookie=None):
        body = json.dumps(payload, ensure_ascii=False).encode() if isinstance(payload, (dict, list)) else payload
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("Referrer-Policy", "no-referrer")
        if cookie:
            self.send_header("Set-Cookie", f"{COOKIE}={cookie}; HttpOnly; SameSite=Strict; Path=/")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def safe_origin(self) -> bool:
        port = self.server.server_port
        allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
        host = self.headers.get("Host", "")
        if host not in allowed:
            self.send(403, {"error": "Разрешен только локальный адрес сервера"})
            return False
        origin = self.headers.get("Origin")
        if origin and origin != f"http://{host}":
            self.send(403, {"error": "Запрос с другого источника отклонен"})
            return False
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            self.send(403, {"error": "Межсайтовый запрос отклонен"})
            return False
        return True

    def session(self, create=False):
        cookies = SimpleCookie()
        try:
            cookies.load(self.headers.get("Cookie", ""))
            key = cookies[COOKIE].value if COOKIE in cookies else ""
        except Exception:
            key = ""
        item = self.server.get_session(key, create)
        if not item:
            self.send(401, {"error": "Сеанс завершен. Перезагрузи страницу; исходник можно сохранить перед этим."})
        return item

    def do_GET(self):  # noqa: N802
        if not self.safe_origin():
            return
        path = urlsplit(self.path).path
        if path in STATIC:
            filename, mime = STATIC[path]
            self.send(200, files("rpaoias.web").joinpath("static", filename).read_bytes(), mime)
            return
        if path == "/favicon.ico":
            self.send(204, b"", "image/x-icon")
            return
        if path == "/api/examples":
            self.send(200, [{"id": key, "name": name, "source": source_for(key)} for key, name in EXAMPLE_NAMES.items()])
            return
        if path not in ("/api/session", "/api/state") and not path.startswith("/api/history/"):
            self.send(404, {"error": "Адрес не найден"})
            return
        item = self.session(create=path == "/api/session")
        if not item:
            return
        sid, token, session, _ = item
        with session.lock:
            if path == "/api/session":
                self.send(200, {"token": token, **session.state(True)}, cookie=sid)
            elif path == "/api/state":
                self.send(200, session.state(True))
            else:
                try:
                    ident = int(path.rsplit("/", 1)[-1])
                except ValueError:
                    ident = -1
                row = next((x for x in session.history if x["id"] == ident), None)
                self.send(200 if row else 404, row or {"error": "Шаг уже удален из истории"})

    def do_POST(self):  # noqa: N802
        if not self.safe_origin():
            return
        if urlsplit(self.path).path != "/api/action":
            self.send(404, {"error": "Адрес не найден"})
            return
        item = self.session()
        if not item:
            return
        if not secrets.compare_digest(self.headers.get("X-CSRF-Token", ""), item[1]):
            self.send(403, {"error": "Неверный токен сеанса"})
            return
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip() != "application/json":
            self.send(415, {"error": "Нужен JSON"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= MAX_BODY:
                self.send(413, {"error": "Запрос слишком большой или пустой"})
                return
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict):
                raise ValueError("Нужен объект JSON")
        except (ValueError, UnicodeError):
            self.send(400, {"error": "Неверный JSON"})
            return
        session = item[2]
        with session.lock:
            if body.get("revision") != session.revision:
                self.send(409, {"error": "Состояние изменилось в другой вкладке. Обнови состояние.",
                                "state": session.state(True)})
                return
            action = body.get("action")
            try:
                if action == "assemble":
                    session.assemble(body.get("source"))
                elif action == "example":
                    session.assemble(source_for(body.get("name", "")))
                elif action == "reset":
                    session.reset()
                elif action == "step":
                    session.step()
                elif action == "run_to_halt":
                    session.run_to_halt()
                else:
                    raise ValueError("Неизвестное действие")
            except (EmulatorError, ValueError, TypeError) as exc:
                self.send(400, {"error": str(exc), "state": session.state()})
                return
            self.send(200, session.state(action in ("assemble", "example")))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Локальный веб-интерфейс учебного CPU")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error("Порт должен быть в диапазоне 0..65535")
    try:
        server = LocalServer(("127.0.0.1", args.port))
    except OSError as exc:
        print(f"Не удалось открыть порт {args.port}: {exc}\nПопробуй --port 8081")
        return 1
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"Открой {url}\nОстановка сервера: Ctrl+C. Доступ только с этого компьютера.", flush=True)
    if not args.no_browser:
        timer = Timer(0.6, lambda: webbrowser.open(url))
        timer.daemon = True
        timer.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
