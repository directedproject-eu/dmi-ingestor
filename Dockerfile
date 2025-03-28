FROM python:3.12

RUN apt-get update \
 && apt-get install --assume-yes --no-install-recommends  \
        gdal-bin \
        libgdal-dev \
 && rm --recursive --force /var/lib/apt/lists/*

WORKDIR /app

COPY ./requirements.txt ./

RUN pip install -r requirements.txt

COPY dmi_ingester ./dmi_ingester

ENTRYPOINT [ "python", "/app/dmi_ingester/ingester.py"]