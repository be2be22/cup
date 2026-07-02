import os
import json
import sqlite3
import uuid
import functools
from datetime import datetime

from flask import Flask, request, session, redirect, url_for, render_template, flash

# ---------------------------------------------------------------------------
# تنظیمات از متغیرهای محیطی
# ---------------------------------------------------------------------------
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "changeme")
SECRET_KEY = os.environ.get("SECRET_KEY", "please-change-this-secret-key")
WS_PATH = os.environ.get("WS_PATH", "/ws")
XRAY_PORT = int(os.environ.get("XRAY_PORT", "10000"))
PUBLIC_PORT = os.environ.get("PUBLIC_PORT", "443")
PUBLIC_TLS = os.environ.get("PUBLIC_TLS", "true").lower() == "true"
XRAY_CONTAINER_NAME = os.environ.get("XRAY_CONTAINER_NAME", "xray")

DB_PATH = "/data/panel.db"
XRAY_CONFIG_PATH = "/etc/xray/config.json"

app = Flask(__name__)
app.secret_key = SECRET_KEY


# ---------------------------------------------------------------------------
# دیتابیس
# ---------------------------------------------------------------------------
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            uuid TEXT NOT NULL UNIQUE,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# تولید کانفیگ Xray و ری‌استارت کانتینر
# ---------------------------------------------------------------------------
def rebuild_xray_config():
    conn = get_db()
    rows = conn.execute(
        "SELECT uuid, name FROM clients WHERE enabled = 1"
    ).fetchall()
    conn.close()

    clients = [{"id": r["uuid"], "email": r["name"]} for r in rows]

    config = {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "listen": "0.0.0.0",
                "port": XRAY_PORT,
                "protocol": "vless",
                "settings": {
                    "clients": clients,
                    "decryption": "none",
                },
                "streamSettings": {
                    "network": "ws",
                    "wsSettings": {"path": WS_PATH},
                },
            }
        ],
        "outbounds": [{"protocol": "freedom"}],
    }

    with open(XRAY_CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)

    restart_xray()


def restart_xray():
    """با استفاده از داکر سوکت، کانتینر xray را ری‌استارت می‌کند تا کانفیگ جدید لود شود."""
    try:
        import docker

        client = docker.from_env()
        container = client.containers.get(XRAY_CONTAINER_NAME)
        container.restart(timeout=5)
    except Exception as e:
        # اگر ری‌استارت خودکار ممکن نبود، حداقل کانفیگ روی دیسک نوشته شده
        app.logger.warning("Could not restart xray container automatically: %s", e)


# ---------------------------------------------------------------------------
# احراز هویت
# ---------------------------------------------------------------------------
def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if username == ADMIN_USER and password == ADMIN_PASS:
            session["logged_in"] = True
            return redirect(url_for("dashboard"))
        flash("نام کاربری یا رمز عبور اشتباه است", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# ابزار ساخت لینک اشتراک‌گذاری VLESS
# ---------------------------------------------------------------------------
def build_share_link(client_uuid, name, host):
    security = "tls" if PUBLIC_TLS else "none"
    params = (
        f"type=ws&security={security}&path={WS_PATH}&host={host}"
        if security == "none"
        else f"type=ws&security=tls&path={WS_PATH}&host={host}&sni={host}"
    )
    return f"vless://{client_uuid}@{host}:{PUBLIC_PORT}?{params}#{name}"


# ---------------------------------------------------------------------------
# صفحات مدیریتی
# ---------------------------------------------------------------------------
@app.route("/")
@login_required
def dashboard():
    conn = get_db()
    clients = conn.execute(
        "SELECT * FROM clients ORDER BY created_at DESC"
    ).fetchall()
    conn.close()

    host = request.host.split(":")[0]
    clients_with_links = []
    for c in clients:
        link = build_share_link(c["uuid"], c["name"], host)
        clients_with_links.append({**dict(c), "link": link})

    return render_template(
        "dashboard.html",
        clients=clients_with_links,
        ws_path=WS_PATH,
    )


@app.route("/add", methods=["POST"])
@login_required
def add_client():
    name = request.form.get("name", "").strip() or "client"
    new_uuid = str(uuid.uuid4())

    conn = get_db()
    conn.execute(
        "INSERT INTO clients (name, uuid, enabled, created_at) VALUES (?, ?, 1, ?)",
        (name, new_uuid, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()

    rebuild_xray_config()
    flash(f"کاربر «{name}» ساخته شد", "success")
    return redirect(url_for("dashboard"))


@app.route("/toggle/<int:client_id>", methods=["POST"])
@login_required
def toggle_client(client_id):
    conn = get_db()
    row = conn.execute(
        "SELECT enabled FROM clients WHERE id = ?", (client_id,)
    ).fetchone()
    if row:
        new_state = 0 if row["enabled"] else 1
        conn.execute(
            "UPDATE clients SET enabled = ? WHERE id = ?", (new_state, client_id)
        )
        conn.commit()
    conn.close()

    rebuild_xray_config()
    return redirect(url_for("dashboard"))


@app.route("/delete/<int:client_id>", methods=["POST"])
@login_required
def delete_client(client_id):
    conn = get_db()
    conn.execute("DELETE FROM clients WHERE id = ?", (client_id,))
    conn.commit()
    conn.close()

    rebuild_xray_config()
    flash("کاربر حذف شد", "success")
    return redirect(url_for("dashboard"))


init_db()
# در شروع، کانفیگ Xray را با وضعیت فعلی دیتابیس هماهنگ می‌کنیم
rebuild_xray_config()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
