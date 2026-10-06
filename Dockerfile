FROM python:3.14

# WeasyPrint 70 loads Pango, Cairo, and HarfBuzz when it is imported.
# GDK-Pixbuf and shared-mime-info are part of that image library set.
# fonts-dejavu-core supplies glyphs for the PDF smoke.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libcairo2 \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libharfbuzz-subset0 \
        libgdk-pixbuf-2.0-0 \
        shared-mime-info \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Non-zero uid. gunicorn starts only after USER, so it is not root.
RUN groupadd --gid 1000 iggybase \
    && useradd --uid 1000 --gid iggybase --create-home --shell /usr/sbin/nologin iggybase

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=iggybase:iggybase . .

USER iggybase

EXPOSE 8000

# FLASK_DEBUG and DEBUG stay unset. No --reload.
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "run:iggybase"]
