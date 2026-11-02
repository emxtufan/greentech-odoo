FROM odoo:19.0
USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-venv python3-dev build-essential libpq-dev libldap2-dev libsasl2-dev \
    && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv --system-site-packages /opt/finance-venv
COPY source/requirements.txt /tmp/finance-requirements.txt
RUN /opt/finance-venv/bin/pip install --no-cache-dir -r /tmp/finance-requirements.txt
COPY source/ /opt/finance-source/
COPY addons/ /opt/finance-addons/
COPY container_restore.py /opt/finance-tools/container_restore.py
ENV PYTHONDONTWRITEBYTECODE=1
WORKDIR /opt/finance-source
USER odoo
ENTRYPOINT ["/opt/finance-venv/bin/python", "/opt/finance-source/odoo-bin"]
CMD ["-c", "/etc/odoo/finance.conf"]
