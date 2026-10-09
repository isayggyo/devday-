from functools import lru_cache

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from .config import get_settings


class ObjectStore:
    def __init__(self, bucket=None):
        settings = get_settings()
        self.bucket = bucket or settings.s3_bucket
        self.client = boto3.client("s3", endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key.get_secret_value(),
            aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
            region_name=settings.s3_region,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}, connect_timeout=3, read_timeout=15,
                retries={"max_attempts": 1}, request_checksum_calculation="when_required", response_checksum_validation="when_required"))

    def initialize(self):
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError as error:
            if error.response["ResponseMetadata"]["HTTPStatusCode"] != 404:
                raise
            self.client.create_bucket(Bucket=self.bucket)

    def put(self, key, data, content_type):
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    def get(self, key):
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        try:
            return response["Body"].read()
        finally:
            response["Body"].close()

    def delete(self, key):
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def delete_prefix(self, prefix):
        pages = self.client.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=prefix)
        for page in pages:
            keys = [{"Key": item["Key"]} for item in page.get("Contents", [])]
            if keys:
                result = self.client.delete_objects(Bucket=self.bucket, Delete={"Objects": keys})
                if result.get('Errors'):
                    raise RuntimeError('OBJECT_DELETE_FAILED')


@lru_cache
def get_object_store():
    return ObjectStore()


if __name__ == "__main__":
    try:
        store = get_object_store()
        store.initialize()
        ObjectStore(get_settings().s3_test_bucket).initialize()
    except Exception:
        raise SystemExit(1)
