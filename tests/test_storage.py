from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock

import boto3
from botocore.exceptions import ClientError
from botocore.response import StreamingBody
from botocore.stub import Stubber
from fastapi import UploadFile
import pytest

from app.services import storage


@pytest.fixture
def s3(monkeypatch):
    # Explicit dummy credentials prevent any credential-provider network access.
    client = boto3.client("s3", region_name="eu-central-1",
                          aws_access_key_id="test", aws_secret_access_key="test")
    monkeypatch.setattr(storage, "settings", SimpleNamespace(
        storage_backend="s3", s3_bucket="smoke-test-bucket", s3_region="eu-central-1"))
    monkeypatch.setattr(storage, "_s3_client", lambda: client)
    with Stubber(client) as stub:
        yield client, stub
        stub.assert_no_pending_responses()


async def test_s3_upload_preserves_bytes_and_sets_content_type(s3, monkeypatch):
    client, _ = s3
    received = []

    def upload(file, bucket, key, ExtraArgs):
        received.append((file.read(), bucket, key, ExtraArgs))

    monkeypatch.setattr(client, "upload_fileobj", upload)
    source = BytesIO(b"hello storage")
    source.seek(5)
    upload_file = UploadFile(source, filename="file.txt")
    key = storage.make_storage_key(1, "unique", "../../file.txt")
    assert key == "1/unique/file.txt"
    assert await storage.save_upload_file(upload_file, key) == 13
    assert received == [(b"hello storage", "smoke-test-bucket", key,
                         {"ContentType": "application/octet-stream"})]
    source.close()


async def test_s3_download_stream_and_delete(s3):
    _, stub = s3
    params = {"Bucket": "smoke-test-bucket", "Key": "1/file.txt"}
    stub.add_response("head_object", {}, params)
    raw = BytesIO(b"download content")
    stub.add_response("get_object", {"Body": StreamingBody(raw, 16)}, params)
    stub.add_response("delete_object", {}, params)
    assert await storage.storage_file_exists("1/file.txt") is True
    response = await storage.download_storage_file("1/file.txt", 'file".txt', "text/plain")
    assert b"".join([chunk async for chunk in response.body_iterator]) == b"download content"
    assert raw.closed
    assert response.headers["content-disposition"] == 'attachment; filename="file.txt"'
    await storage.delete_storage_file("1/file.txt")


@pytest.mark.parametrize("code", ["404", "NoSuchKey", "NotFound", "AccessDenied"])
async def test_s3_missing_object_vs_service_failure(s3, code):
    _, stub = s3
    stub.add_client_error("head_object", service_error_code=code,
                          http_status_code=403 if code == "AccessDenied" else 404,
                          expected_params={"Bucket": "smoke-test-bucket", "Key": "missing"})
    if code == "AccessDenied":
        with pytest.raises(ClientError):
            await storage.storage_file_exists("missing")
    else:
        assert await storage.storage_file_exists("missing") is False


async def test_s3_stream_closes_on_read_error(s3):
    _, stub = s3
    body = Mock()
    body.read.side_effect = OSError("stream interrupted")
    stub.add_response("get_object", {"Body": body},
                      {"Bucket": "smoke-test-bucket", "Key": "broken"})
    response = await storage.download_storage_file("broken", "file.txt", "text/plain")
    with pytest.raises(OSError, match="stream interrupted"):
        async for _ in response.body_iterator:
            pass
    body.close.assert_called_once()
