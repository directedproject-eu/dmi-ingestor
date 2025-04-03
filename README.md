# DMI forecast data ingestion for DIRECTED project

Build the Docker image:
```shell
docker build . -t directed/dmi-ingestor:latest
```

Run the Docker image for sea level data (is the default):
```shell
docker run -e DMI_API_KEY="" -e BUCKET_NAME="" -e BUCKET_KEY="" -e BUCKET_SECRET="" directed/dmi-ingestor:latest
```

Run the Docker image for precipitation data:
```shell
docker run -e DMI_API_KEY="" -e BUCKET_NAME="" -e BUCKET_KEY="" -e BUCKET_SECRET="" -e COLLECTION="harmonie_dini_sf" -e BBOX="1180,150,1300,280" -e PARAMETERS="total-precipitation,rain-precipitation-rate" directed/dmi-ingestor:latest
```
Note: for collections using the Lambert conformal conic projection (`harmonie_*`) the DMI API expects the bbox to be in km not m!