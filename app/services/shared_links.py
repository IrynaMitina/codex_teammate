import secrets

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


async def get_public_file(db: AsyncSession, token: str) -> File:
    result = await db.execute(
        select(File)
        .join(SharedLink, SharedLink.file_id == File.id)
        .where(SharedLink.token == token, File.deleted_at.is_(None))
    )
    db_file = result.scalar_one_or_none()
    if not db_file or not await storage_file_exists(db_file.storage_key):
        raise HTTPException(status_code=404, detail="Shared file not found")
    return db_file
