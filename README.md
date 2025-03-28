```shell
docker build . -t directed/dmi-ingestor:latest
docker run -e DMI_API_KEY="" -e BUCKET_NAME="" -e BUCKET_KEY="" -e BUCKET_SECRET="" directed/dmi-ingestor:latest
```