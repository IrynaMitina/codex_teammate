import pytest
from io import BytesIO
from fastapi import HTTPException, UploadFile


from app.models.folder import Folder
from app.models.permission import Permission
from app.models.user import User
from app.schemas.drive import FolderCreate, ShareCreate
from app.services import folders as folder_service
from app.services import permissions as permission_service
from app.services.access import has_access
from app.services import files as file_service
from app.services import shared_links as link_service


@pytest.mark.asyncio
async def test_create_folder_service(seeded_db):
    user = await seeded_db.get(User, 1)

    folder = await folder_service.create_folder(
        db=seeded_db,
        current_user=user,
        payload=FolderCreate(name="docs", parent_id=None),
    )

    assert folder.id is not None
    assert folder.name == "docs"
    assert folder.owner_id == user.id


@pytest.mark.asyncio
async def test_owner_has_access_to_folder(seeded_db):
    user = await seeded_db.get(User, 1)

    folder = Folder(
        owner_id=user.id,
        parent_id=None,
        name="docs",
    )
    seeded_db.add(folder)
    await seeded_db.commit()
    await seeded_db.refresh(folder)

    assert await has_access(seeded_db, user, "folder", folder.id, "viewer") is True
    assert await has_access(seeded_db, user, "folder", folder.id, "editor") is True


@pytest.mark.asyncio
async def test_shared_viewer_has_viewer_access_only(seeded_db):
    alice = await seeded_db.get(User, 1)
    bob = await seeded_db.get(User, 2)

    folder = Folder(
        owner_id=alice.id,
        parent_id=None,
        name="docs",
    )
    seeded_db.add(folder)
    await seeded_db.commit()
    await seeded_db.refresh(folder)

    permission = Permission(
        user_id=bob.id,
        resource_type="folder",
        resource_id=folder.id,
        role="viewer",
    )
    seeded_db.add(permission)
    await seeded_db.commit()

    assert await has_access(seeded_db, bob, "folder", folder.id, "viewer") is True
    assert await has_access(seeded_db, bob, "folder", folder.id, "editor") is False


@pytest.mark.asyncio
async def test_share_resource_service(seeded_db):
    alice = await seeded_db.get(User, 1)

    folder = Folder(
        owner_id=alice.id,
        parent_id=None,
        name="docs",
    )
    seeded_db.add(folder)
    await seeded_db.commit()
    await seeded_db.refresh(folder)

    permission = await permission_service.share_resource(
        db=seeded_db,
        current_user=alice,
        resource_type="folder",
        resource_id=folder.id,
        payload=ShareCreate(user_id=2, role="viewer"),
    )

    assert permission.id is not None
    assert permission.user_id == 2
    assert permission.resource_type == "folder"
    assert permission.resource_id == folder.id
    assert permission.role == "viewer"


async def test_file_sharing_lifecycle(seeded_db, temp_storage):
    alice = await seeded_db.get(User, 1)
    bob = await seeded_db.get(User, 2)
    folder = await folder_service.create_folder(seeded_db, alice, FolderCreate(name="lifecycle"))
    upload = UploadFile(BytesIO(b"service-level content"), filename="service.txt")
    try:
        file = await file_service.upload_file(seeded_db, alice, folder.id, upload)
    finally:
        await upload.close()
    assert file.size_bytes == len(b"service-level content")
    assert (await file_service.get_file_for_download(seeded_db, alice, file.id)).id == file.id
    with pytest.raises(HTTPException) as denied:
        await file_service.get_file_for_download(seeded_db, bob, file.id)
    assert denied.value.status_code == 403
    permission = await permission_service.share_resource(
        seeded_db, alice, "file", file.id, ShareCreate(user_id=2, role="viewer"))
    assert (await file_service.get_file_for_download(seeded_db, bob, file.id)).id == file.id
    # Viewing must not grant delete or re-sharing rights.
    with pytest.raises(HTTPException) as denied:
        await file_service.delete_file(seeded_db, bob, file.id)
    assert denied.value.status_code == 403
    with pytest.raises(HTTPException) as denied:
        await permission_service.share_resource(
            seeded_db, bob, "file", file.id, ShareCreate(user_id=1, role="editor"))
    assert denied.value.status_code == 403
    link = await link_service.create_shared_link(seeded_db, alice, file.id)
    assert (await link_service.get_public_file(seeded_db, link.token)).id == file.id
    await permission_service.remove_permission(seeded_db, alice, permission.id)
    assert await permission_service.list_permissions(seeded_db, alice, "file", file.id) == []
    with pytest.raises(HTTPException) as denied:
        await file_service.get_file_for_download(seeded_db, bob, file.id)
    assert denied.value.status_code == 403
    # Revoking Bob does not revoke the independently issued public link.
    assert (await link_service.get_public_file(seeded_db, link.token)).id == file.id
    await file_service.delete_file(seeded_db, alice, file.id)
    await seeded_db.refresh(file)
    assert await folder_service.list_folder_contents(seeded_db, alice, folder.id) == {
        "folders": [], "files": []}
    with pytest.raises(HTTPException) as missing:
        await link_service.get_public_file(seeded_db, link.token)
    assert missing.value.status_code == 404
    with pytest.raises(HTTPException) as missing:
        await link_service.create_shared_link(seeded_db, alice, file.id)
    assert missing.value.status_code == 404


async def test_deleted_parent_hides_children_and_files(seeded_db, temp_storage):
    alice = await seeded_db.get(User, 1)
    parent = await folder_service.create_folder(seeded_db, alice, FolderCreate(name="parent"))
    child = await folder_service.create_folder(
        seeded_db, alice, FolderCreate(name="child", parent_id=parent.id))
    upload = UploadFile(BytesIO(b"content"), filename="child.txt")
    try:
        file = await file_service.upload_file(seeded_db, alice, parent.id, upload)
    finally:
        await upload.close()
    contents = await folder_service.list_folder_contents(seeded_db, alice, parent.id)
    assert [f.id for f in contents["folders"]] == [child.id]
    assert [f.id for f in contents["files"]] == [file.id]
    await folder_service.delete_folder(seeded_db, alice, parent.id)
    await seeded_db.refresh(parent)
    await seeded_db.refresh(child)
    await seeded_db.refresh(file)
    assert child.deleted_at is not None
    assert file.deleted_at is not None
    with pytest.raises(HTTPException) as denied:
        await folder_service.list_folder_contents(seeded_db, alice, parent.id)
    assert denied.value.status_code == 403
