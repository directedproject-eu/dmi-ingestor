FROM python:3.13-slim

#
# Fight OS CVEs and install dependencies
#
RUN apt-get update \
 && apt-get upgrade -y \
 && apt-get dist-upgrade -y \
 && apt-get install --assume-yes --no-install-recommends  \
        build-essential \
        gdal-bin \
        libgdal-dev

WORKDIR /app

COPY ./requirements.txt ./

RUN pip install -r requirements.txt

RUN apt-get update \
 && apt-get remove --assume-yes build-essential \
 && apt-get clean \
 && apt autoremove -y  \
 && rm -rf /var/lib/apt/lists/*

COPY dmi_ingestor ./dmi_ingestor

ENTRYPOINT [ "python", "/app/dmi_ingestor/ingestor.py"]
