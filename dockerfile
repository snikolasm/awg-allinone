FROM vnxme/amneziawg-go:latest

# Автоматически определяем версию Alpine и подключаем репозиторий community
RUN echo "https://dl-cdn.alpinelinux.org/alpine/v$(cut -d. -f1,2 /etc/alpine-release)/community" >> /etc/apk/repositories \
    && apk update \
    && apk add --no-cache python3 py3-pip qrencode curl

# Ставим Flask напрямую, обходя защиту PEP 668
RUN pip3 install --no-cache-dir --break-system-packages flask

RUN mkdir -p /opt/awg-panel/configs /opt/awg-panel/qr /opt/awg-panel/templates
COPY app.py /opt/awg-panel/app.py
COPY index.html /opt/awg-panel/templates/index.html
EXPOSE 8080
CMD ["python3", "/opt/awg-panel/app.py"]
