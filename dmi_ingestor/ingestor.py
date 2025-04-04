import json
import logging
import os
import sys
from collections import namedtuple
from io import BytesIO
from urllib.parse import urlencode, urlunsplit

import pyproj
import requests
import xarray
from osgeo import gdal
from requests.exceptions import HTTPError
from s3fs import S3FileSystem


# Necessary to avoid writing checksums into the COGs when uploading them to the bucket (cf. https://github.com/boto/boto3/issues/4435)
os.environ["AWS_REQUEST_CHECKSUM_CALCULATION"] = "when_required"
os.environ["AWS_RESPONSE_CHECKSUM_VALIDATION"] = "when_required"

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

# see https://opendatadocs.dmi.govcloud.dk/Data/Forecast_Data_Weather_Model_HARMONIE_DINI_IG
LCC_DMI_WKT = """PROJCRS["DMI HARMONIE DINI lambert projection",
BASEGEOGCRS["DMI HARMONIE DINI lambert CRS",
    DATUM["DMI HARMONIE DINI lambert datum",
        ELLIPSOID["Sphere",6371229,0,
            LENGTHUNIT["metre",1,
                ID["EPSG",9001]]]],
    PRIMEM["Greenwich",0,
        ANGLEUNIT["degree",0.0174532925199433,
            ID["EPSG",9122]]]],
CONVERSION["Lambert Conic Conformal (2SP)",
    METHOD["Lambert Conic Conformal (2SP)",
        ID["EPSG",9802]],
    PARAMETER["Latitude of false origin",55.5,
        ANGLEUNIT["degree",0.0174532925199433],
        ID["EPSG",8821]],
    PARAMETER["Longitude of false origin",-8,
        ANGLEUNIT["degree",0.0174532925199433],
        ID["EPSG",8822]],
    PARAMETER["Latitude of 1st standard parallel",55.5,
        ANGLEUNIT["degree",0.0174532925199433],
        ID["EPSG",8823]],
    PARAMETER["Latitude of 2nd standard parallel",55.5,
        ANGLEUNIT["degree",0.0174532925199433],
        ID["EPSG",8824]],
    PARAMETER["Easting at false origin",0,
        LENGTHUNIT["metre",1],
        ID["EPSG",8826]],
    PARAMETER["Northing at false origin",0,
        LENGTHUNIT["metre",1],
        ID["EPSG",8827]]],
CS[Cartesian,2],
    AXIS["(E)",east,
        ORDER[1],
        LENGTHUNIT["Metre",1]],
    AXIS["(N)",north,
        ORDER[2],
        LENGTHUNIT["Metre",1]]]"""

def delete_outdated_forecasts(bucket_path, endpoint_url, key, secret):
    logger.debug(f"Delete path {bucket_path} recursively.")
    s3 = S3FileSystem(
        endpoint_url=endpoint_url,
        key=key,
        secret=secret
    )
    try:
        s3.rm(bucket_path, recursive=True)
    except FileNotFoundError as err:
        logger.debug(err)


def netcdf_to_cog(input_file, output_file):
    dataset = gdal.Open(input_file)
    options = gdal.TranslateOptions(format="COG", creationOptions=["COMPRESS=LZW"], outputSRS="EPSG:4326")
    gdal.Translate(output_file, dataset, options=options)
    dataset = None


def reproject_from_lambert(xarray_dataset, crs_to="epsg:4326"):
    crs_from = pyproj.CRS.from_wkt(LCC_DMI_WKT)
    xarray_dataset.rio.write_crs(crs_from, inplace=True)
    xarray_dataset = xarray_dataset.rio.reproject(crs_to)
    return xarray_dataset


def transform_cog_to_single_bands_and_upload_to_bucket(cog_file, folder_name, times, bucket_name=None, bucket_path=None,
                                                       endpoint=None, key=None, secret=None, upload=False):
    dataset = gdal.Open(cog_file)
    forecasts = {}
    for band, t in enumerate(times):
        time_str = str(t).split('.')[0].replace("-", "").replace(":", "")
        output_file = os.path.join(folder_name, time_str + ".tif")
        gdal.Translate(output_file, dataset, bandList=[band+1], options=["BIGTIFF=YES"])
        if upload:
            upload_to_bucket(output_file, f"{bucket_name}/{bucket_path}/{os.path.basename(output_file)}",
                             endpoint, key, secret)
            forecasts[time_str] = f"https://{bucket_name}.{endpoint.lstrip('https://')}/{bucket_path}/{os.path.basename(output_file)}"
            if band % 10 == 0:
                logger.info(f"Uploaded {band} of {len(times)} files.")
    dataset = None
    return forecasts


def upload_to_bucket(local_file, bucket_file, endpoint_url, key, secret):
    logger.debug(f"Try to upload {local_file} to {bucket_file}.")
    s3 = S3FileSystem(
        endpoint_url=endpoint_url,
        key=key,
        secret=secret
    )
    with open(local_file, 'rb') as f:
        with s3.open(bucket_file, 'wb') as s3_file:
            s3_file.write(f.read())
            logger.debug("Upload succeeded.")


if __name__ == "__main__":
    logger.info("Start ingesting DMI data.")
    # Configurable parameters
    dmi_api_key = os.getenv("DMI_API_KEY")
    bucket_endpoint = os.getenv("BUCKET_ENDPOINT", "https://obs.eu-de.otc.t-systems.com")
    bucket_name = os.getenv("BUCKET_NAME")
    bucket_base_path = os.getenv("BUCKET_BASE_PATH", "data/dmi/forecasts")
    bucket_key = os.getenv("BUCKET_KEY")
    bucket_secret = os.getenv("BUCKET_SECRET")
    upload = os.getenv("UPLOAD_TO_BUCKET", "true").lower() == "true"
    collection = os.getenv("COLLECTION", "dkss_if")
    parameters = os.getenv("PARAMETERS", "sea-mean-deviation")
    bbox = os.getenv("BBOX", "11.5,55.5,12.2,56.1")
    # Fixed parameters
    netloc = "dmigw.govcloud.dk"
    url_base_path = "v1/forecastedr/collections"
    request_type = "cube"
    out_format = "NetCDF"  # the API is case-sensitive!
    base_data_dir = "/app/data"
    nc_filename = os.path.join(base_data_dir, "temp.nc")
    cog_filename = os.path.join(base_data_dir, "temp.tif")
    forecast_json_filename = os.path.join(base_data_dir, "forecasts.json")

    for parameter in parameters.split(","):
        logger.info(f"Start ingesting data from collection '{collection}' for parameter '{parameter}'.")
        bucket_path = f"{bucket_base_path}/{collection}/{parameter}"
        bucket_path_full = f"{bucket_name}/{bucket_path}"
        forecast_json_bucket_path = bucket_path_full + "/forecasts.json"
        if not os.path.exists(base_data_dir):
            os.makedirs(base_data_dir)

        Parts = namedtuple(
            typename='Components',
            field_names=['scheme', 'netloc', 'path', 'query', 'fragment']
        )

        if collection.startswith("harmonie"):
            crs = "native"
        else:
            crs = "crs84"

        query_params = {
            "api-key": dmi_api_key,
            "crs": crs,
            "parameter-name": parameter,
            "bbox": bbox,
            "f": out_format
        }

        url = urlunsplit(
            Parts(
                scheme="https",
                netloc=netloc,
                path=f"{url_base_path}/{collection}/{request_type}",
                query=urlencode(query_params),
                fragment=''
            )
        )
        try:
            logger.info(f"Request data from DMI API.")
            response = requests.get(url)
            response.raise_for_status()
        except HTTPError as err:
            logger.error(err)
        else:
            delete_outdated_forecasts(bucket_path_full, bucket_endpoint, bucket_key, bucket_secret)
            ds = xarray.open_dataset(BytesIO(response.content))
            if collection.startswith("harmonie"):
                ds = reproject_from_lambert(ds)
            logger.info(f"Save data to NetCDF.")
            ds.to_netcdf(nc_filename)
            logger.info(f"Transform NetCDF to COG.")
            netcdf_to_cog(nc_filename, cog_filename)
            logger.info(f"Split COG into bands (time slices) and upload them to bucket.")
            data = transform_cog_to_single_bands_and_upload_to_bucket(
                cog_filename, base_data_dir, ds.time.values, bucket_name, bucket_path, bucket_endpoint, bucket_key,
                bucket_secret, upload)
            with open(forecast_json_filename, "w", encoding="utf-8") as fp:
                json.dump(data, fp, indent=4)
            upload_to_bucket(forecast_json_filename, forecast_json_bucket_path,
                             bucket_endpoint, bucket_key, bucket_secret)
            try:
                os.remove(nc_filename)
                os.remove(cog_filename)
                os.remove(forecast_json_filename)
            except Exception as err:
                logger.warning(err)
