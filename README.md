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

## Run with Docker

Build the image from the repository root:

```bash
docker build -t drive-api:local .
```

Create `.env.docker` for a local container:

```dotenv
APP_ENV=dev
DATABASE_URL_TEMPLATE=sqlite+aiosqlite:////data/drive.db
STORAGE_BACKEND=local
JWT_SECRET_KEY=replace-with-a-random-secret
```

Initialize a persistent volume, run migrations, and start the API:

```bash
docker volume create drive-data
docker run --rm --env-file .env.docker -v drive-data:/data drive-api:local alembic upgrade head
docker run --rm --name drive-api --env-file .env.docker -v drive-data:/data -p 127.0.0.1:8000:8000 drive-api:local
```

Open `http://127.0.0.1:8000/docs`. To add demo users locally, run:

```bash
docker run --rm --env-file .env.docker -v drive-data:/data drive-api:local python -m app.db.seed
```

The container runs as UID/GID `10001:10001`, listens on port `8000`, and
writes logs to stdout/stderr. Local uploads default to `/data/storage`.
Bind-mounted data directories must be writable by that UID. Environment
files, credentials, local data, and development files are excluded from the
build context; configuration is supplied at runtime.

For ECS, configure container port `8000`, `STORAGE_BACKEND=s3`, `S3_BUCKET`,
and `S3_REGION`. Use a database URL such as
`postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@database-host:5432/drive` in
`DATABASE_URL_TEMPLATE`, and inject `DB_USER`, `DB_PASSWORD`, and
`JWT_SECRET_KEY` from Secrets Manager. Use an ECS task role for S3 access.
Build for the task's CPU architecture (for example, add
`--platform linux/amd64` to `docker build` for an x86_64 task).

Run `alembic upgrade head` as a separate one-off task using the same image,
database configuration, and network access before starting the service.
Migrations and demo seeding do not run automatically on API startup.
The existing `/docs` route can serve as an HTTP liveness check; it does not
check database or S3 connectivity. Promote the same image from staging to
production as described in [the architecture](docs/architecture.md).

## AWS infrastructure templates

See [infra/README.md](infra/README.md) for the shared ECR repository and isolated
staging/production CloudFormation stacks, deployment steps, and migrations.

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

## CI/CD pipeline

GitHub Actions runs tests and enforces **82% application coverage**. After a
merge to `main`, AWS builds the image, deploys to staging, and runs smoke tests.
Production requires manual approval and receives the same tested image digest.

### One-time setup

1. **Enable CI.** Merge [the workflow](.github/workflows/ci.yml) and the
   [CD files](infra/README.md#continuous-delivery-drive-6) into `main`. After the
   first CI run, configure a GitHub branch ruleset for `main`: require pull
   requests, the `Tests and coverage` check, and an up-to-date branch. Block
   direct pushes; AWS starts on pushes to `main` without waiting for CI.
2. **Prepare AWS environments.** In one AWS account and region, follow the
   [bootstrap instructions](infra/README.md#bootstrap-and-deploy) to deploy
   `drive-images`, `drive-staging`, and `drive-production`, then run initial
   migrations. Update existing stacks with the current templates to add the
   exports required by the pipeline, preserving their parameters and images.
3. **Connect GitHub.** In AWS CodeConnections, create and authorize a connection
   for this repository. Wait until its status is `AVAILABLE` and save its ARN.
4. **Configure smoke tests.** Provision two distinct staging test accounts.
   Create a Secrets Manager JSON secret in the same region, using the default
   AWS managed key, with `alice_email`, `alice_password`, `bob_email`,
   `bob_password`, and `bob_user_id` (Bob's actual positive database ID).
   Save its ARN; keep passwords out of the repository.
5. **Create the pipeline.** Set `CONNECTION_ARN` and `SMOKE_SECRET_ARN` to the
   saved ARNs. With AWS CLI credentials for the target account and region, run:

```bash
aws cloudformation deploy \
  --template-file infra/pipeline.yaml --stack-name drive-cd \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
    ConnectionArn="$CONNECTION_ARN" \
    GitHubRepository=IrynaMitina/codex_teammate \
    ImageStackName=drive-images \
    StagingStackName=drive-staging \
    ProductionStackName=drive-production \
    SmokeSecretArn="$SMOKE_SECRET_ARN"
```

Setup creates billable AWS resources and may start the first release. Open the
stack's `PipelineUrl` output, confirm staging deployment and `SmokeTesting`
succeed, then approve `ApproveProduction` using an identity authorized for
`codepipeline:PutApprovalResult`. Future merges run the same sequence automatically,
pausing for production approval each time.

See [the AWS pipeline guide](infra/README.md#continuous-delivery-drive-6) for
permissions, migration handling, and troubleshooting.

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
