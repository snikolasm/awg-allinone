# Берем готовый образ с AmneziaWG (userspace)
FROM ghcr.io/ayastrebov/docker-amneziawg:latest

# Устанавливаем Python и зависимости для панели
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    qrencode \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Устанавливаем Flask
RUN pip3 install flask

# Создаем папки для панели
RUN mkdir -p /opt/awg-panel/configs /opt/awg-panel/qr /opt/awg-panel/templates

# Копируем файлы панели (app.py и index.html) внутрь образа
COPY app.py /opt/awg-panel/app.py
COPY index.html /opt/awg-panel/templates/index.html

# Открываем порт для веб-панели (по умолчанию Flask на 8080)
EXPOSE 2020

# Запускаем панель (она сама запустит awg через subprocess)
CMD ["python3", "/opt/awg-panel/app.py"]