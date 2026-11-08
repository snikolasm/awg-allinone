FROM debian:13-slim

# Устанавливаем утилиты для добавления репозитория и работы сети
RUN apt-get update && apt-get install -y \
    curl \
    gnupg \
    python3 \
    python3-pip \
    python3-venv \
    qrencode \
    iproute2 \
    iptables \
    && rm -rf /var/lib/apt/lists/*

# Добавляем ключ и репозиторий Amnezia для Debian 13 (используем noble, т.к. glibc совместим) [citation:8][citation:24]
RUN mkdir -p /etc/apt/keyrings && \
    curl -fsSL "https://keyserver.ubuntu.com/pks/lookup?op=get&search=0x75C9DD72C799870E310542E24166F2C2572908" | gpg --dearmor -o /etc/apt/keyrings/amnezia.gpg && \
    echo "deb [signed-by=/etc/apt/keyrings/amnezia.gpg] https://ppa.launchpadcontent.net/amnezia/ppa/ubuntu noble main" > /etc/apt/sources.list.d/amnezia.list

# Устанавливаем amneziawg-tools и amneziawg-go (userspace реализация, не требует модуля ядра хоста)
RUN apt-get update && apt-get install -y \
    amneziawg-tools \
    amneziawg-go \
    && rm -rf /var/lib/apt/lists/*

# Создаем виртуальное окружение и ставим Flask
RUN python3 -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir flask

# Создаем папки для панели
RUN mkdir -p /opt/awg-panel/configs /opt/awg-panel/qr /opt/awg-panel/templates

# Копируем файлы панели
COPY app.py /opt/awg-panel/app.py
COPY index.html /opt/awg-panel/templates/index.html

EXPOSE 2020

# Запускаем панель
CMD ["/opt/venv/bin/python3", "/opt/awg-panel/app.py"]
