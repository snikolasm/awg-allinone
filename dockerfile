# Используем образ, который точно основан на Alpine (vnxme/amneziawg-go)
# НО! Если вы хотите именно Debian 13, вам нужен другой базовый образ с awg.
# Если оставляем Alpine (так как vnxme/amneziawg-go на нем), то используем apk.
# Если переходим на Debian, нужно искать или собирать amneziawg-go для Debian.

# ПРЕДПОЛАГАЕМ, ЧТО ВЫ ХОТИТЕ ОСТАТЬСЯ НА ALPINE (vnxme), НО ПРАВИЛЬНО СТАВИТЬ PYTHON
FROM vnxme/amneziawg-go:latest

# В Alpine правильные пакеты: python3, py3-pip, py3-venv
# Но если репозитории не работают, используем venv, который требует py3-venv
RUN apk add --no-cache python3 py3-pip py3-venv qrencode curl

# Создаем виртуальное окружение и ставим Flask
RUN python3 -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir flask

# Создаем папки
RUN mkdir -p /opt/awg-panel/configs /opt/awg-panel/qr /opt/awg-panel/templates

# Копируем файлы
COPY app.py /opt/awg-panel/app.py
COPY index.html /opt/awg-panel/templates/index.html

EXPOSE 8080

# Запускаем через Python из venv
CMD ["/opt/venv/bin/python3", "/opt/awg-panel/app.py"]
