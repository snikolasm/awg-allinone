# Используем образ, который точно содержит amneziawg-go и основан на Alpine
FROM vnxme/amneziawg-go:latest

# Устанавливаем Python, pip и venv. 
# Для Alpine правильные имена пакетов: python3, py3-pip, py3-venv.
RUN apk add --no-cache python3 py3-pip py3-venv qrencode curl

# Создаем виртуальное окружение и ставим Flask в него.
# Это обходит ограничения PEP 668 в Alpine.
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir flask

# Создаем папки для панели
RUN mkdir -p /opt/awg-panel/configs /opt/awg-panel/qr /opt/awg-panel/templates

# Копируем файлы панели
COPY app.py /opt/awg-panel/app.py
COPY index.html /opt/awg-panel/templates/index.html

# Открываем порт (у вас указан 2020, но в app.py Flask слушает 8080)
EXPOSE 8080

# Запускаем панель через Python из виртуального окружения
CMD ["/opt/venv/bin/python3", "/opt/awg-panel/app.py"]
