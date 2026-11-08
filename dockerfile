FROM vnxme/amneziawg-go:latest

# Устанавливаем только python3 и pip, без venv
RUN apk add --no-cache python3 py3-pip qrencode curl

# Ставим Flask напрямую, обходя защиту PEP 668
RUN pip3 install --no-cache-dir --break-system-packages flask

RUN mkdir -p /opt/awg-panel/configs /opt/awg-panel/qr /opt/awg-panel/templates
COPY app.py /opt/awg-panel/app.py
COPY index.html /opt/awg-panel/templates/index.html
EXPOSE 8080
CMD ["python3", "/opt/awg-panel/app.py"]
