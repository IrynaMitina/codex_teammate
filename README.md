# Git Drive REST API Base

This project is a small Google Drive-like REST backend built with FastAPI. It supports JWT login, folder creation, file upload/download, soft deletion, and resource sharing through `viewer` and `editor` permissions.


## Quick Start

Create a local `.env.dev`:

```bash
cat > .env.dev <<'EOF'
APP_ENV=dev
DEBUG=true
LOG_LEVEL=INFO
DATABASE_URL_TEMPLATE=sqlite+aiosqlite:///./drive.db
STORAGE_BACKEND=local
STORAGE_DIR=./storage
JWT_SECRET_KEY=dev-secret-change-me
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
EOF
```

Install dependencies, migrate the database, seed demo users, and launch the API:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
python -m app.db.seed
uvicorn app.main:app --reload
```

The backend runs at `http://127.0.0.1:8000`.

Swagger UI is available at `http://127.0.0.1:8000/docs`.

## S3 setup

Local storage is used by default. Set `STORAGE_BACKEND=s3` in `.env.dev` (or
the environment file selected by `APP_ENV`) to store uploaded files in Amazon
S3.

```dotenv
STORAGE_BACKEND=s3
S3_BUCKET=my-drive-bucket
S3_REGION=eu-central-1
```

Configuration variables:

| Variable | Required | Description |
| --- | --- | --- |
| `STORAGE_BACKEND` | Yes | Set to `s3`. The default is `local`. |
| `S3_BUCKET` | Yes | Name of the bucket used to store file objects. |
| `S3_REGION` | No | AWS region containing the bucket, such as `eu-central-1`. |

AWS credentials are deliberately not configured in the application's `.env`
file. Boto3 uses its standard credential provider chain:

- When running locally, it reads credentials from `~/.aws/credentials`. The
  `default` profile is used unless `AWS_PROFILE` selects another profile.
- When running in AWS, it automatically obtains temporary credentials from the
  IAM role attached to the runtime, such as an ECS task role, EKS pod identity,
  or EC2 instance profile.

For local development, configure a profile with the AWS CLI and optionally
select it before starting the API:

```bash
aws configure --profile drive-dev
export AWS_PROFILE=drive-dev
uvicorn app.main:app --reload
```

Do not store long-lived AWS access keys in `.env.dev` or commit them to source
control.

The application identity needs permission to perform these operations on
objects in the configured bucket:

- `s3:PutObject` for uploads
- `s3:GetObject` for downloads and existence checks
- `s3:DeleteObject` for file deletion

The bucket must already exist; the application does not create it. After
updating the environment file, restart the API for the new backend settings to
take effect. `STORAGE_DIR` is ignored while the S3 backend is selected.

## Run Tests

```bash
python -m pytest
```

## Typical Local Scenario With curl

Set the API address once. Using this variable also keeps the commands safe to
copy from Markdown renderers that automatically turn full URLs into links:

```bash
API_URL="http://127.0.0.1:8000"
```

Login as Alice:

```bash
ALICE_TOKEN=$(curl -fsS -X POST "$API_URL/api/v1/auth/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=alice@example.com&password=alice123" \
  | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
```

Login as Bob:

```bash
BOB_TOKEN=$(curl -fsS -X POST "$API_URL/api/v1/auth/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=bob@example.com&password=bob123" \
  | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
```

Create a folder as Alice:

```bash
FOLDER_NAME="docs-$(date +%s)"
FOLDER_ID=$(curl -fsS -X POST "$API_URL/api/v1/drive/folders" \
  -H "Authorization: Bearer $ALICE_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"$FOLDER_NAME\",\"parent_id\":null}" \
  | python -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "$FOLDER_ID"
```

Upload a file into the created folder:

```bash
printf "hello shared drive\n" > /tmp/a.txt
FILE_ID=$(curl -fsS -X POST "$API_URL/api/v1/drive/folders/$FOLDER_ID/files" \
  -H "Authorization: Bearer $ALICE_TOKEN" \
  -F "upload=@/tmp/a.txt;type=text/plain" \
  | python -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "$FILE_ID"
```

List the folder contents:

```bash
curl -fsS "$API_URL/api/v1/drive/folders/$FOLDER_ID/contents" \
  -H "Authorization: Bearer $ALICE_TOKEN"
```

Verify Bob cannot download the file yet:

```bash
curl -i "$API_URL/api/v1/drive/files/$FILE_ID/download" \
  -H "Authorization: Bearer $BOB_TOKEN"
```

Share the file with Bob as a viewer:

```bash
curl -fsS -X POST "$API_URL/api/v1/drive/file/$FILE_ID/share" \
  -H "Authorization: Bearer $ALICE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"user_id":2,"role":"viewer"}'
```

Download the file as Bob:

```bash
curl -fsS "$API_URL/api/v1/drive/files/$FILE_ID/download" \
  -H "Authorization: Bearer $BOB_TOKEN"
```

Create a public **shared link** as the file owner:

```bash
SHARED_URL=$(curl -fsS -X POST "$API_URL/api/v1/drive/files/$FILE_ID/shared-links" \
  -H "Authorization: Bearer $ALICE_TOKEN" \
  | python -c "import sys,json; print(json.load(sys.stdin)['download_url'])")
echo "$SHARED_URL"
```

Anyone with that link can download the file without signing in:

```bash
curl -fsS "$API_URL$SHARED_URL"
```

Delete the file as Alice:

```bash
curl -i -X DELETE "$API_URL/api/v1/drive/files/$FILE_ID" \
  -H "Authorization: Bearer $ALICE_TOKEN"
```
