#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import sqlite3
import subprocess
import threading
import time
import ipaddress
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, request, Response, render_template, jsonify, send_file

# ==================== Конфигурация ====================
AUTH_USER = "snm"
AUTH_PASS = "2xxlmanII"
INTERFACE = "awg0"
SERVER_CONF = "/etc/amnezia/amneziawg/awg0.conf"
DB_PATH = "/opt/awg-panel/panel.db"
CONFIGS_DIR = "/opt/awg-panel/configs"
QR_DIR = "/opt/awg-panel/qr"

DEFAULT_MTU = "1280"
DEFAULT_KEEPALIVE = "25"

app = Flask(__name__)
os.makedirs(CONFIGS_DIR, exist_ok=True)
os.makedirs(QR_DIR, exist_ok=True)

# ==================== Работа с серверным конфигом ====================
def get_server_config():
    if not os.path.exists(SERVER_CONF):
        raise RuntimeError(f"Файл {SERVER_CONF} не найден.")

    with open(SERVER_CONF, "r") as f:
        content = f.read()

    m_priv = re.search(r"^PrivateKey\s*=\s*(\S+)", content, re.MULTILINE)
    if not m_priv:
        raise RuntimeError("В конфиге сервера не найден PrivateKey")
    priv = m_priv.group(1)
    srv_pub = subprocess.run(["awg", "pubkey"], input=priv, capture_output=True, text=True).stdout.strip()

    m_port = re.search(r"^ListenPort\s*=\s*(\d+)", content, re.MULTILINE)
    port = m_port.group(1) if m_port else "51820"

    m_addr = re.search(r"^Address\s*=\s*(\S+)", content, re.MULTILINE)
    if not m_addr:
        raise RuntimeError("В конфиге сервера не найден Address")
    
    server_ip_str = m_addr.group(1).split('/')[0]
    server_ip = ipaddress.ip_address(server_ip_str)
    network = ipaddress.ip_network(f"{server_ip_str}/24", strict=False)

    m_mtu = re.search(r"^MTU\s*=\s*(\d+)", content, re.MULTILINE)
    mtu = m_mtu.group(1) if m_mtu else DEFAULT_MTU

    m_keepalive = re.search(r"^PersistentKeepalive\s*=\s*(\d+)", content, re.MULTILINE)
    keepalive = m_keepalive.group(1) if m_keepalive else DEFAULT_KEEPALIVE

    obfuscation = {}
    for param in ["Jc", "Jmin", "Jmax", "S1", "S2", "S3", "S4", "H1", "H2", "H3", "H4"]:
        m = re.search(rf"^{param}\s*=\s*(\d+)", content, re.MULTILINE)
        if m:
            obfuscation[param] = m.group(1)

    return {
        "pub_key": srv_pub, "port": port, "network": network,
        "server_ip": server_ip, "mtu": mtu, "keepalive": keepalive,
        "obfuscation": obfuscation
    }

def append_peer_to_conf(pub_key, allowed_ip):
    """Дописывает пира в конец файла серверного конфига"""
    peer_block = f"""
[Peer]
PublicKey = {pub_key}
AllowedIPs = {allowed_ip}/32
"""
    with open(SERVER_CONF, "a") as f:
        f.write(peer_block)

def remove_peer_from_conf(pub_key):
    """Удаляет блок пира из серверного конфига по его публичному ключу"""
    if not os.path.exists(SERVER_CONF):
        return
    with open(SERVER_CONF, "r") as f:
        content = f.read()

    # Регулярное выражение для поиска блока [Peer] с нужным ключом
    # Ищем от [Peer] до следующего [Peer] или до конца файла
    pattern = re.compile(
        rf"\[Peer\]\s*\n(?:.*\n)*?PublicKey\s*=\s*{re.escape(pub_key)}\s*\n(?:.*\n)*?(?=\[Peer\]|\Z)",
        re.MULTILINE
    )
    
    new_content = pattern.sub("", content)
    
    # Убираем лишние пустые строки в конце
    new_content = re.sub(r'\n{3,}', '\n\n', new_content).strip() + "\n"
    
    with open(SERVER_CONF, "w") as f:
        f.write(new_content)

# ==================== Определение IP ====================
def get_public_ip():
    try:
        route_out = subprocess.check_output(["ip", "route", "get", "8.8.8.8"], text=True)
        match = re.search(r"dev\s+(\w+)", route_out)
        if match:
            dev = match.group(1)
            addr_out = subprocess.check_output(["ip", "-4", "addr", "show", dev], text=True)
            ip_match = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)", addr_out)
            if ip_match:
                return ip_match.group(1)
    except Exception:
        pass
    return "ВАШ_IP_НЕ_ОПРЕДЕЛЕН"

SERVER_IP = os.environ.get("AWG_SERVER_IP", get_public_ip())
print(f"[*] Панель использует IP для Endpoint: {SERVER_IP}")

# ==================== БД и Утилиты ====================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS clients (
            name TEXT PRIMARY KEY,
            pub_key TEXT NOT NULL,
            ip TEXT NOT NULL,
            expire_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

def check_auth(username, password):
    return username == AUTH_USER and password == AUTH_PASS

def authenticate():
    return Response('Требуется авторизация', 401, {'WWW-Authenticate': 'Basic realm="AWG Panel"'})

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated

def run_cmd(cmd, check=True, input_data=None):
    result = subprocess.run(cmd, capture_output=True, text=True, input=input_data)
    if check and result.returncode != 0:
        raise RuntimeError(f"Команда не удалась: {cmd}\n{result.stderr}")
    return result.stdout

def gen_keypair():
    priv = run_cmd(["awg", "genkey"]).strip()
    pub = run_cmd(["awg", "pubkey"], input_data=priv).strip()
    return priv, pub

def next_client_ip(network, server_ip):
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT ip FROM clients").fetchall()
    conn.close()
    
    used_ips = {ip for (ip,) in rows}
    used_ips.add(str(server_ip)) 
    
    for ip in network.hosts():
        ip_str = str(ip)
        if ip_str not in used_ips:
            return ip_str
    raise RuntimeError("Свободные IP в подсети закончились")

def add_peer_to_live(pub_key, allowed_ip):
    run_cmd(["awg", "set", INTERFACE, "peer", pub_key, "allowed-ips", f"{allowed_ip}/32"])

def remove_peer_from_live(pub_key):
    run_cmd(["awg", "set", INTERFACE, "peer", pub_key, "remove"], check=False)

# ==================== Фоновая очистка ====================
def cleanup_worker():
    while True:
        try:
            conn = sqlite3.connect(DB_PATH)
            now = datetime.now().isoformat()
            expired = conn.execute("SELECT name, pub_key FROM clients WHERE expire_at < ?", (now,)).fetchall()
            for name, pub in expired:
                remove_peer_from_live(pub)
                remove_peer_from_conf(pub) # Удаляем из файла сервера!
                
                conn.execute("DELETE FROM clients WHERE name = ?", (name,))
                conf_path = os.path.join(CONFIGS_DIR, f"{name}.conf")
                qr_path = os.path.join(QR_DIR, f"{name}.png")
                if os.path.exists(conf_path): os.remove(conf_path)
                if os.path.exists(qr_path): os.remove(qr_path)
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[!] Ошибка очистки: {e}")
        time.sleep(3600)

# ==================== Маршруты ====================
@app.route("/")
@requires_auth
def index():
    return render_template("index.html")

@app.route("/api/server/status")
@requires_auth
def api_server_status():
    try:
        cfg = get_server_config()
        return jsonify({
            "status": "running", "ip": SERVER_IP, "port": cfg["port"],
            "network": str(cfg["network"]), "mtu": cfg["mtu"], "keepalive": cfg["keepalive"]
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/clients")
@requires_auth
def api_clients():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT name, pub_key, ip, expire_at FROM clients ORDER BY name").fetchall()
    conn.close()

    stats_map = {}
    try:
        dump = run_cmd(["awg", "show", INTERFACE, "dump"], check=False)
        for line in dump.strip().split("\n")[1:]:
            parts = line.split("\t")
            if len(parts) >= 8:
                stats_map[parts[0]] = {
                    "rx": int(parts[5]) if parts[5].isdigit() else 0,
                    "tx": int(parts[6]) if parts[6].isdigit() else 0,
                    "handshake": int(parts[4]) if parts[4].isdigit() else 0,
                }
    except Exception:
        pass

    result = []
    for name, pub, ip, expire_at in rows:
        s = stats_map.get(pub, {"rx": 0, "tx": 0, "handshake": 0})
        result.append({
            "name": name, "ip": ip, "expire_at": expire_at,
            "rx": s["rx"], "tx": s["tx"], "last_handshake": s["handshake"],
        })
    return jsonify(result)

@app.route("/api/clients", methods=["POST"])
@requires_auth
def api_client_add():
    data = request.get_json()
    name = (data.get("name") or "").strip()
    days = int(data.get("days", 0))
    
    if not name or days <= 0:
        return jsonify({"ok": False, "message": "Укажите имя и дни (>0)"}), 400

    conn = sqlite3.connect(DB_PATH)
    try:
        if conn.execute("SELECT 1 FROM clients WHERE name = ?", (name,)).fetchone():
            return jsonify({"ok": False, "message": "Имя уже существует"}), 400

        cfg = get_server_config()
        priv, pub = gen_keypair()
        client_ip = next_client_ip(cfg["network"], cfg["server_ip"])

        # 1. Добавляем в память ядра (чтобы работало сразу)
        add_peer_to_live(pub, client_ip)
        # 2. Дописываем в файл сервера (чтобы выжило после перезагрузки)
        append_peer_to_conf(pub, client_ip)

        obf_lines = "\n".join([f"{k} = {v}" for k, v in cfg["obfuscation"].items()])
        config_text = f"""[Interface]
PrivateKey = {priv}
Address = {client_ip}/32
MTU = {cfg["mtu"]}
DNS = 8.8.8.8
{obf_lines}

[Peer]
PublicKey = {cfg["pub_key"]}
Endpoint = {SERVER_IP}:{cfg["port"]}
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = {cfg["keepalive"]}
"""
        
        conf_path = os.path.join(CONFIGS_DIR, f"{name}.conf")
        with open(conf_path, "w") as f:
            f.write(config_text)

        qr_path = os.path.join(QR_DIR, f"{name}.png")
        subprocess.run(["qrencode", "-o", qr_path, "-t", "PNG"], input=config_text.encode(), check=True)

        expire_at = (datetime.now() + timedelta(days=days)).isoformat()
        conn.execute(
            "INSERT INTO clients (name, pub_key, ip, expire_at, created_at) VALUES (?,?,?,?,?)",
            (name, pub, client_ip, expire_at, datetime.now().isoformat()),
        )
        conn.commit()

        return jsonify({"ok": True, "message": "Клиент создан"})
    except Exception as e:
        conn.rollback()
        return jsonify({"ok": False, "message": str(e)}), 500
    finally:
        conn.close()

@app.route("/api/clients/<name>/config")
@requires_auth
def api_client_config(name):
    conf_path = os.path.join(CONFIGS_DIR, f"{name}.conf")
    if os.path.exists(conf_path):
        return send_file(conf_path, as_attachment=True, download_name=f"{name}.conf")
    return "Файл не найден", 404

@app.route("/api/clients/<name>/qr")
@requires_auth
def api_client_qr(name):
    qr_path = os.path.join(QR_DIR, f"{name}.png")
    if os.path.exists(qr_path):
        return send_file(qr_path, mimetype='image/png')
    return "QR-код не найден", 404

# ==================== Аудит системы ====================
@app.route("/api/system/audit")
@requires_auth
def api_system_audit():
    kernel_peers = set()
    try:
        dump = run_cmd(["awg", "show", INTERFACE, "dump"], check=False)
        for line in dump.strip().split("\n")[1:]:
            parts = line.split("\t")
            if len(parts) > 0 and parts[0]:
                kernel_peers.add(parts[0])
    except Exception:
        pass

    conn = sqlite3.connect(DB_PATH)
    db_clients = {row[1]: {"name": row[0], "ip": row[2]} for row in conn.execute("SELECT name, pub_key, ip FROM clients").fetchall()}
    conn.close()

    missing_in_kernel = []
    orphaned_in_kernel = []
    missing_files = []

    for pub_key, info in db_clients.items():
        if pub_key not in kernel_peers:
            missing_in_kernel.append({"name": info["name"], "pub_key": pub_key, "ip": info["ip"]})
        
        conf_path = os.path.join(CONFIGS_DIR, f"{info['name']}.conf")
        if not os.path.exists(conf_path):
            missing_files.append(info["name"])

    for pub_key in kernel_peers:
        if pub_key not in db_clients:
            orphaned_in_kernel.append({"pub_key": pub_key})

    return jsonify({
        "missing_in_kernel": missing_in_kernel,
        "orphaned_in_kernel": orphaned_in_kernel,
        "missing_files": missing_files
    })

@app.route("/api/system/audit/clean", methods=["POST"])
@requires_auth
def api_system_audit_clean():
    data = request.get_json()
    action = data.get("action")
    pub_key = data.get("pub_key")
    name = data.get("name")

    try:
        if action == "remove_orphan" and pub_key:
            remove_peer_from_live(pub_key)
            remove_peer_from_conf(pub_key) # Удаляем и из файла
            return jsonify({"ok": True, "message": "Фантомный пир удален"})

        elif action == "remove_broken" and name and pub_key:
            remove_peer_from_live(pub_key)
            remove_peer_from_conf(pub_key) # Удаляем и из файла
            
            conn = sqlite3.connect(DB_PATH)
            conn.execute("DELETE FROM clients WHERE name = ?", (name,))
            conn.commit()
            conn.close()
            
            conf_path = os.path.join(CONFIGS_DIR, f"{name}.conf")
            qr_path = os.path.join(QR_DIR, f"{name}.png")
            if os.path.exists(conf_path): os.remove(conf_path)
            if os.path.exists(qr_path): os.remove(qr_path)
            
            return jsonify({"ok": True, "message": "Битая запись удалена"})
            
        return jsonify({"ok": False, "message": "Неизвестное действие"}), 400
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500

if __name__ == "__main__":
    init_db()
    threading.Thread(target=cleanup_worker, daemon=True).start()
    app.run(host="0.0.0.0", port=8080, debug=False)