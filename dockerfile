# Используем образ, который точно содержит amneziawg-go и основан на Alpine
FROM vnxme/amneziawg-go:latest

# Устанавливаем Python и pip. 
# Пакет py3-pip находится в репозитории community, который в этом образе уже должен быть подключен.
RUN apk add --no-cache python3 py3-pip qrencode curl

# Создаем виртуальное окружение и ставим Flask в него.
# Используем ensurepip, если venv не сработает, но сначала пробуем стандартный путь.
RUN python3 -m venv /opt/venv || (python3 -m ensurepip && pip3 install --no-cache-dir --break-system-packages flask && exit 0) \
    && if [ -d /opt/venv ]; then /opt/venv/bin/pip install --no-cache-dir flask; fi

# Создаем папки для панели
RUN mkdir -p /opt/awg-panel/configs /opt/awg-panel/qr /opt/awg-panel/templates

# Копируем файлы панели
COPY app.py /opt/awg-panel/app.py
COPY index.html /opt/awg-panel/templates/index.html

# Открываем порт (в app.py Flask слушает 8080)
EXPOSE 8080

# Запускаем панель. Проверяем, есть ли venv, и используем его, иначе системный python3.
CMD ["sh", "-c", "if [ -f /opt/venv/bin/python3 ]; then /opt/venv/bin/python3 /opt/awg-panel/app.py; else python3 /opt/awg-panel/app.py; fi"]
