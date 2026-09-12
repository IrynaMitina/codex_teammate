# app/services/storage.py
import asyncio
import os
from collections.abc import AsyncIterator

import aiofiles
from fastapi import UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from app.core.config import get_settings


settings = get_settings()
STORAGE_DIR = settings.storage_dir


def make_storage_key(user_id: int, file_uuid: str, filename: str) -> str:
    """Return the backend-specific key persisted with a file record."""
    safe_filename = os.path.basename(filename.replace("\\", "/")) or "uploaded_file"
    relative_key = "/".join((str(user_id), file_uuid, safe_filename))
    if settings.storage_backend == "s3":
        return relative_key
    return os.path.join(STORAGE_DIR, *relative_key.split("/"))


def _s3_client():
    # Import lazily so local-only deployments do not initialize the AWS SDK.
    import boto3

    return boto3.client(
        "s3",
        region_name=settings.s3_region,
    )


async def save_upload_file(upload_file: UploadFile, storage_key: str) -> int:
    if settings.storage_backend == "s3":
        await upload_file.seek(0)
        size = await asyncio.to_thread(_file_size, upload_file.file)
        await asyncio.to_thread(
            _s3_client().upload_fileobj,
            upload_file.file,
            settings.s3_bucket,
            storage_key,
            ExtraArgs={"ContentType": upload_file.content_type or "application/octet-stream"},
        )
        return size

    os.makedirs(os.path.dirname(storage_key), exist_ok=True)

    size = 0

    async with aiofiles.open(storage_key, "wb") as out_file:
        while chunk := await upload_file.read(1024 * 1024):
            size += len(chunk)
            await out_file.write(chunk)

    return size


def _file_size(file_object) -> int:
    current_position = file_object.tell()
    file_object.seek(0, os.SEEK_END)
    size = file_object.tell()
    file_object.seek(current_position)
    return size


async def storage_file_exists(storage_key: str) -> bool:
    if settings.storage_backend == "s3":
        client = _s3_client()
        try:
            await asyncio.to_thread(
                client.head_object,
                Bucket=settings.s3_bucket,
                Key=storage_key,
            )
            return True
        except client.exceptions.ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise
    return os.path.exists(storage_key)


async def download_storage_file(storage_key: str, filename: str, media_type: str):
    if settings.storage_backend == "local":
        return FileResponse(path=storage_key, filename=filename, media_type=media_type)

    response = await asyncio.to_thread(
        _s3_client().get_object,
        Bucket=settings.s3_bucket,
        Key=storage_key,
    )
    body = response["Body"]

    async def chunks() -> AsyncIterator[bytes]:
        try:
            while chunk := await asyncio.to_thread(body.read, 1024 * 1024):
                yield chunk
        finally:
            body.close()

    safe_filename = filename.replace('"', "")
    return StreamingResponse(
        chunks(),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{safe_filename}"'},
    )


async def delete_storage_file(storage_key: str) -> None:
    if settings.storage_backend == "s3":
        await asyncio.to_thread(
            _s3_client().delete_object,
            Bucket=settings.s3_bucket,
            Key=storage_key,
        )
    elif os.path.exists(storage_key):
        os.remove(storage_key)
