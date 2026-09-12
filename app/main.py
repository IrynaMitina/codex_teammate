# app/main.py
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.router import router as v1_router
from app.core.config import get_settings
from app.core.logging import setup_logging

setup_logging()

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    if settings.storage_backend == "s3":
        logger.info(
            "Storage backend: s3 (bucket=%s, region=%s)",
            settings.s3_bucket,
            settings.s3_region or "default",
        )
    else:
        logger.info("Storage backend: local (directory=%s)", settings.storage_dir)

    yield


app = FastAPI(lifespan=lifespan)

app.include_router(
    v1_router,
    prefix="/api/v1",
)
