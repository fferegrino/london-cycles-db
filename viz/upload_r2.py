"""Upload a file to Cloudflare R2, replacing any object of the same key.

The README embeds the coverage graph from R2 rather than from the repo, so
refreshing it does not add a commit to `main` every day. The object is stored
with a one-hour Cache-Control so GitHub's image proxy refetches it.
"""

import mimetypes
import os
from pathlib import Path

import typer

CACHE_CONTROL = "public, max-age=3600"


def upload_to_r2(
    file_path: Path,
    key: str | None = None,
    *,
    account_id: str | None = None,
    access_key_id: str | None = None,
    secret_access_key: str | None = None,
    bucket: str | None = None,
    public_base_url: str | None = None,
    cache_control: str = CACHE_CONTROL,
) -> str:
    import boto3
    from botocore.config import Config

    account = account_id or os.environ.get("R2_ACCOUNT_ID")
    access_key = access_key_id or os.environ.get("R2_ACCESS_KEY_ID")
    secret_key = secret_access_key or os.environ.get("R2_SECRET_ACCESS_KEY")
    bucket_name = bucket or os.environ.get("R2_BUCKET")
    missing = [
        name
        for name, value in (
            ("R2_ACCOUNT_ID", account),
            ("R2_ACCESS_KEY_ID", access_key),
            ("R2_SECRET_ACCESS_KEY", secret_key),
            ("R2_BUCKET", bucket_name),
        )
        if not value
    ]
    if missing:
        raise ValueError(f"Missing R2 configuration: {', '.join(missing)}")

    object_key = key or file_path.name
    content_type = "image/svg+xml" if file_path.suffix == ".svg" else mimetypes.guess_type(file_path.name)[0]
    content_type = content_type or "application/octet-stream"

    client = boto3.client(
        "s3",
        endpoint_url=f"https://{account}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )
    print(f"Uploading {file_path} to R2 as {object_key} in bucket {bucket_name}...")
    client.put_object(
        Bucket=bucket_name,
        Key=object_key,
        Body=file_path.read_bytes(),
        ContentType=content_type,
        CacheControl=cache_control,
    )

    base = (public_base_url or os.environ.get("R2_PUBLIC_BASE_URL") or "").rstrip("/")
    url = f"{base}/{object_key}" if base else object_key
    print(f"Uploaded to R2: {url}")
    return url


def main(
    file_path: Path = typer.Argument(..., exists=True, dir_okay=False, help="File to upload."),
    key: str | None = typer.Option(None, "--key", help="Object key in the bucket. Defaults to the file's name."),
    cache_control: str = typer.Option(CACHE_CONTROL, "--cache-control", help="Cache-Control stored on the object."),
):
    upload_to_r2(file_path=file_path, key=key, cache_control=cache_control)


if __name__ == "__main__":
    typer.run(main)
