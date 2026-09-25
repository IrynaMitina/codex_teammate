import secrets
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.file import File
from app.models.shared_link import SharedLink
from app.models.user import User
from app.services.storage import storage_file_exists


async def create_shared_link(
    db: AsyncSession,
    current_user: User,
    file_id: int,
) -> SharedLink:
    db_file = await db.get(File, file_id)
    if not db_file or db_file.deleted_at:
        raise HTTPException(status_code=404, detail="File not found")
    if db_file.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the file owner can create a shared link")

    shared_link = SharedLink(file_id=file_id, token=secrets.token_urlsafe(32))
    db.add(shared_link)
    await db.commit()
    await db.refresh(shared_link)
    return shared_link


async def revoke_shared_link(
    db: AsyncSession,
    current_user: User,
    token: str,
) -> None:
    shared_link = await db.scalar(select(SharedLink).where(SharedLink.token == token))
    if not shared_link:
        raise HTTPException(status_code=404, detail="Shared link not found")
    db_file = await db.get(File, shared_link.file_id)
    if not db_file:
        raise HTTPException(status_code=404, detail="File not found")
    if db_file.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the file owner can revoke a shared link")
    if shared_link.revoked_at is None:
        shared_link.revoked_at = datetime.now(timezone.utc)
        await db.commit()


async def get_public_file(db: AsyncSession, token: str) -> File:
    shared_link = await db.scalar(select(SharedLink).where(SharedLink.token == token))
    if not shared_link:
        raise HTTPException(status_code=404, detail="Shared file not found")
    if shared_link.revoked_at is not None:
        raise HTTPException(status_code=401, detail="Shared link has been revoked")
    db_file = await db.get(File, shared_link.file_id)
    if (
        not db_file
        or db_file.deleted_at
        or not await storage_file_exists(db_file.storage_key)
    ):
        raise HTTPException(status_code=404, detail="Shared file not found")
    return db_file
