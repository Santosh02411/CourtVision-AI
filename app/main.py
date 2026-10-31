"""Flask application factory, security headers, SPA shell and the Socket.IO live loop."""
from __future__ import annotations

import hashlib
import json
import logging
import time
from threading import Lock

from flask import Flask, jsonify, render_template, request
from flask_socketio import SocketIO

from app.config import Config
from app.services import teams as T
from app.services.cache import DataUnavailable
from app.services.util import today_et

logging.basicConfig(level=logging.DEBUG if Config.DEBUG else logging.INFO,
                    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
logger = logging.getLogger("courtvision")

socketio = SocketIO(async_mode="threading")
_loop_started = False
_loop_lock = Lock()
_clients = 0

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; "
       "img-src 'self' data: https://cdn.nba.com https://a.espncdn.com; connect-src 'self' ws: wss:; "
       "frame-ancestors 'none'; base-uri 'self'; form-action 'self'")


def create_app(services=None) -> Flask:
    from app.api.routes import Services, bp, legacy

    app = Flask(__name__)
    app.config["SECRET_KEY"] = Config.resolve_secret()
    app.config["JSON_SORT_KEYS"] = False
    app.config["SERVICES"] = services or Services()
    app.json.compact = True

    socketio.init_app(app, cors_allowed_origins=Config.CORS_ORIGINS or None)
    app.register_blueprint(bp)
    app.register_blueprint(legacy)

    @app.after_request
    def headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        if resp.mimetype == "text/html":
            resp.headers.setdefault("Content-Security-Policy", CSP)
            resp.headers["Cache-Control"] = "no-cache"
        elif request.path.startswith("/api/"):
            resp.headers.setdefault("Cache-Control", "no-store")
        elif request.path.startswith("/static/"):
            resp.headers.setdefault("Cache-Control", "no-cache" if Config.DEBUG else "public, max-age=3600")
        return resp

    @app.get("/")
    @app.get("/<path:page>")
    def spa(page: str = ""):
        if page.startswith(("api/", "static/", "socket.io")):
            return jsonify({"ok": False, "error": {"code": "not_found", "message": "Not found"}}), 404
        return render_template("index.html", app_name=Config.APP_NAME, tagline=Config.APP_TAGLINE,
                               version=Config.VERSION, season=T.current_season())

    @app.errorhandler(404)
    def not_found(_):
        return jsonify({"ok": False, "error": {"code": "not_found", "message": "Not found"}}), 404

    @socketio.on("connect")
    def on_connect():
        global _clients, _loop_started
        _clients += 1
        with _loop_lock:
            if not _loop_started:
                _loop_started = True
                socketio.start_background_task(_live_loop, app)

    @socketio.on("disconnect")
    def on_disconnect():
        global _clients
        _clients = max(0, _clients - 1)

    return app


def _compact(g: dict) -> dict:
    return {k: g.get(k) for k in ("game_id", "status", "status_text", "period", "clock", "home", "away", "live_wp", "start_utc")}


def _live_loop(app: Flask) -> None:
    """Push the scoreboard to connected clients only while someone is listening, and only when it changed."""
    last_digest, last_emit = "", 0.0
    while True:
        socketio.sleep(Config.LIVE_POLL_SECONDS)
        if not _clients:
            continue
        try:
            services = app.config["SERVICES"]
            games, prov, notes = services.live.games_for_date(today_et())
            payload = {"games": [_compact(g) for g in games], "notes": notes,
                       "status": "stale" if any(p.status == "stale" for p in prov) else "fresh",
                       "server_time": time.time()}
            digest = hashlib.sha1(json.dumps(payload["games"], sort_keys=True, default=str).encode()).hexdigest()
            if digest != last_digest or time.time() - last_emit > 30:
                socketio.emit("scoreboard", payload)
                last_digest, last_emit = digest, time.time()
        except DataUnavailable as exc:
            socketio.emit("scoreboard", {"games": [], "status": "unavailable", "notes": [str(exc)], "server_time": time.time()})
        except Exception:
            logger.exception("live loop iteration failed")
