import os
import re
import sqlite3
import subprocess
import threading
import time
import ipaddress
import secrets
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

# ==================== БАЗА ДАННЫХ ====================
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

# ==================== УТИЛИТЫ ====================
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

def run_cmd(cmd, check=True, input_data=None, shell=False):
    result = subprocess.run(cmd, capture_output=True, text=True, input=input_data, shell=shell)
    if check and result.returncode != 0:
        raise RuntimeError(f"Команда не удалась: {cmd}\n{result.stderr}")
    return result.stdout

def gen_keypair():
    priv = run_cmd(["awg", "genkey"]).strip()
    pub = run_cmd(["awg", "pubkey"], input_data=priv).strip()
    return priv, pub

def setup_firewall(port):
    """Автоматическая настройка UFW (внутри контейнера или через nsenter)"""
    print(f"[*] Попытка настройки файрвола для порта {port}/udp...")
    
    # Проверяем, запущены ли мы в контейнере и есть ли nsenter
    # Если панель работает в network_mode: host, ufw может быть доступен напрямую
    
    cmd_ufw_status = ["ufw", "status"]
    try:
        # Проверяем статус UFW
        status_out = run_cmd(cmd_ufw_status, check=False)
        if "Status: inactive" in status_out:
            print("[*] UFW неактивен. Включаем...")
            run_cmd(["ufw", "allow", "ssh"], check=False) # Не теряем SSH
            run_cmd(["ufw", "--force", "enable"], check=False)
        
        # Добавляем правило, если его нет
        rules = run_cmd(["ufw", "status"], check=False)
        if f"{port}/udp" not in rules:
            print(f"[*] Добавляем правило UFW для порта {port}/udp")
            run_cmd(["ufw", "allow", f"{port}/udp"], check=False)
            print("[+] Правило успешно добавлено.")
        else:
            print(f"[+] Правило для порта {port}/udp уже существует.")
            
    except FileNotFoundError:
        print("[!] UFW не найден внутри контейнера. Пропускаем настройку файрвола.")
    except Exception as e:
        print(f"[!] Ошибка при настройке UFW: {e}")

# ==================== РАБОТА С КОНФИГОМ ====================
def get_server_config():
    if not os.path.exists(SERVER_CONF):
        raise RuntimeError("Файл сервера не найден. Создайте его во вкладке 'Сервер'.")
    
    with open(SERVER_CONF, "r") as f:
        content = f.read()

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
        "port": port, "network": network,
        "server_ip": server_ip, "mtu": mtu, "keepalive": keepalive,
        "obfuscation": obfuscation
    }

# ==================== ФОНОВАЯ ОЧИСТКА ====================
def cleanup_worker():
    while True:
        try:
            conn = sqlite3.connect(DB_PATH)
            now = datetime.now().isoformat()
            expired = conn.execute("SELECT name, pub_key FROM clients WHERE expire_at < ?", (now,)).fetchall()
            for name, pub in expired:
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

# ==================== МАРШРУТЫ ====================
@app.route("/")
@requires_auth
def index():
    return render_template("index.html")

@app.route("/api/server/generate", methods=["POST"])
@requires_auth
def api_server_generate():
    data = request.get_json()
    network = data.get("network", "10.9.9.0/24")
    port = data.get("port", "54443")
    
    try:
        # 1. Открываем порт в файрволе
        setup_firewall(port)

        # 2. Генерируем ключи
        priv, pub = gen_keypair()
        
        # 3. Генерируем параметры обфускации
        jc = secrets.randbelow(5) + 3
        jmin = secrets.randbelow(100) + 50
        jmax = secrets.randbelow(500) + 200
        s1 = secrets.randbelow(50) + 10
        s2 = s1 + 56
        s3 = secrets.randbelow(30) + 10
        s4 = secrets.randbelow(30) + 5
        h1 = secrets.randbelow(2000000000) + 5
        h2 = secrets.randbelow(2000000000) + 5
        h3 = secrets.randbelow(2000000000) + 5
        h4 = secrets.randbelow(2000000000) + 5

        # 4. Формируем конфиг
        config = f"""[Interface]
PrivateKey = {priv}
Address = {network.split('/')[0].rsplit('.', 1)[0]}.1/24
ListenPort = {port}
MTU = 1280

Jc = {jc}
Jmin = {jmin}
Jmax = {jmax}
S1 = {s1}
S2 = {s2}
S3 = {s3}
S4 = {s4}
H1 = {h1}
H2 = {h2}
H3 = {h3}
H4 = {h4}

PostUp = iptables -A FORWARD -i %i -j ACCEPT; iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
PostDown = iptables -D FORWARD -i %i -j ACCEPT; iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE
"""
        
        # 5. Записываем в файл
        os.makedirs(os.path.dirname(SERVER_CONF), exist_ok=True)
        with open(SERVER_CONF, "w") as f:
            f.write(config)
        
        return jsonify({"ok": True, "message": f"Сервер создан, порт {port}/udp открыт."})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500

@app.route("/api/server/status")
@requires_auth
def api_server_status():
    try:
        cfg = get_server_config()
        return jsonify({
            "status": "running", 
            "ip": os.environ.get("AWG_SERVER_IP", "не определен"),
            "port": cfg["port"],
            "network": str(cfg["network"]),
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/clients")
@requires_auth
def api_clients():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT name, pub_key, ip, expire_at FROM clients ORDER BY name").fetchall()
    conn.close()
    return jsonify([{"name": r[0], "ip": r[2], "expire_at": r[3]} for r in rows])

@app.route("/api/clients", methods=["POST"])
@requires_auth
def api_client_add():
    data = request.get_json()
    name = (data.get("name") or "").strip()
    days = int(data.get("days", 0))
    
    if not name or days <= 0:
        return jsonify({"ok": False, "message": "Укажите имя и дни (>0)"}), 400

    try:
        cfg = get_server_config()
        priv, pub = gen_keypair()
        client_ip = f"{str(cfg['network']).split('/')[0].rsplit('.', 1)[0]}.2"

        with open(SERVER_CONF, "r") as f:
            content = f.read()
        
        new_peer = f"""
[Peer]
PublicKey = {pub}
AllowedIPs = {client_ip}/32
"""
        with open(SERVER_CONF, "a") as f:
            f.write(new_peer)

        # Получаем публичный ключ сервера из конфига
        m = re.search(r"^PrivateKey\s*=\s*(\S+)", content, re.MULTILINE)
        srv_pub = run_cmd(["awg", "pubkey"], input_data=m.group(1)).strip() if m else "КЛЮЧ_НЕ_НАЙДЕН"
        
        config_text = f"""[Interface]
PrivateKey = {priv}
Address = {client_ip}/32
MTU = {cfg["mtu"]}
DNS = 8.8.8.8

[Peer]
PublicKey = {srv_pub}
Endpoint = {os.environ.get("AWG_SERVER_IP", "IP_СЕРВЕРА")}:{cfg["port"]}
AllowedIPs = 0.0.0.0/0
"""
        
        conf_path = os.path.join(CONFIGS_DIR, f"{name}.conf")
        with open(conf_path, "w") as f:
            f.write(config_text)

        qr_path = os.path.join(QR_DIR, f"{name}.png")
        subprocess.run(["qrencode", "-o", qr_path, "-t", "PNG"], input=config_text.encode(), check=True)

        conn = sqlite3.connect(DB_PATH)
        expire_at = (datetime.now() + timedelta(days=days)).isoformat()
        conn.execute("INSERT INTO clients (name, pub_key, ip, expire_at) VALUES (?,?,?,?)", (name, pub, client_ip, expire_at))
        conn.commit()
        conn.close()

        return jsonify({"ok": True, "message": "Клиент создан"})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500

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

if __name__ == "__main__":
    init_db()
    threading.Thread(target=cleanup_worker, daemon=True).start()
    app.run(host="0.0.0.0", port=2020, debug=False)
