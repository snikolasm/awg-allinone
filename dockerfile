# Берем готовый образ с AmneziaWG (userspace)
FROM ghcr.io/ayastrebov/docker-amneziawg:latest

# Устанавливаем Python и зависимости для панели
RUN apk add --no-cache python3 py3-pip qrencode curl

# Устанавливаем Flask
RUN pip3 install flask --break-system-packages

# Создаем папки для панели
RUN mkdir -p /opt/awg-panel/configs /opt/awg-panel/qr /opt/awg-panel/templates

# Копируем файлы панели (app.py и index.html) внутрь образа
COPY app.py /opt/awg-panel/app.py
COPY index.html /opt/awg-panel/templates/index.html

# Открываем порт для веб-панели (по умолчанию Flask на 8080)
EXPOSE 2020

# Запускаем панель (она сама запустит awg через subprocess)
CMD ["python3", "/opt/awg-panel/app.py"]
