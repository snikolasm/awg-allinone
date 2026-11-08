# Используем чистый Debian 13
FROM debian:13-slim

# Устанавливаем зависимости для сборки amneziawg-go и Python
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    qrencode \
    curl \
    git \
    build-essential \
    libc6-dev \
    && rm -rf /var/lib/apt/lists/*

# Создаем виртуальное окружение и ставим Flask
RUN python3 -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir flask

# Собираем amneziawg-go из исходников (userspace реализация)
# Это может занять время, но зато бинарник будет внутри контейнера
RUN git clone https://github.com/amnezia-vpn/amneziawg-go.git /tmp/amneziawg-go && \
    cd /tmp/amneziawg-go && \
    make && \
    cp amneziawg-go /usr/local/bin/ && \
    rm -rf /tmp/amneziawg-go

# Создаем папки для панели
RUN mkdir -p /opt/awg-panel/configs /opt/awg-panel/qr /opt/awg-panel/templates

# Копируем файлы панели
COPY app.py /opt/awg-panel/app.py
COPY index.html /opt/awg-panel/templates/index.html

EXPOSE 8080

# Запускаем панель через Python из venv
CMD ["/opt/venv/bin/python3", "/opt/awg-panel/app.py"]
