from uuid import uuid4
import warnings


async def login(client, email, password):
    response = await client.post(
        "/api/v1/auth/token", data={"username": email, "password": password}
    )
    assert response.status_code == 200, "Smoke account login failed"
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def run_drive_scenario(client, *, alice_email, alice_password,
                             bob_email, bob_password, bob_user_id):
    """Exercise all ten steps in DRIVE-7 comment 10203 using only HTTP.

    The client must have no default authentication or cookies. Only resources
    created by this invocation are deleted; existing account data is untouched.
    """
    # 1–2: Alice logs in and creates the scenario folder.
    alice = await login(client, alice_email, alice_password)
    response = await client.post(
        "/api/v1/drive/folders", headers=alice,
        json={"name": "Smoke Test", "parent_id": None},
    )
    assert response.status_code == 201
    folder_id = response.json()["id"]
    file_id = None
    file_deleted = False
    scenario_passed = False
    try:
        # 3: Upload unique content and verify the folder listing.
        content = f"DRIVE-7 smoke test {uuid4()}\n".encode()
        response = await client.post(
            f"/api/v1/drive/folders/{folder_id}/files", headers=alice,
            files={"upload": ("smoke.txt", content, "text/plain")},
        )
        assert response.status_code == 201
        file_id = response.json()["id"]
        response = await client.get(
            f"/api/v1/drive/folders/{folder_id}/contents", headers=alice
        )
        assert response.status_code == 200
        assert any(f["id"] == file_id and f["name"] == "smoke.txt"
                   and f["size_bytes"] == len(content)
                   for f in response.json()["files"])
        download = f"/api/v1/drive/files/{file_id}/download"
        # 4: Owner download must preserve the original bytes.
        response = await client.get(download, headers=alice)
        assert response.status_code == 200
        assert response.content == content
        # 5: Bob cannot download before sharing.
        bob = await login(client, bob_email, bob_password)
        assert (await client.get(download, headers=bob)).status_code == 403
        # 6–7: Share as viewer; Bob can now download the same bytes.
        response = await client.post(
            f"/api/v1/drive/file/{file_id}/share", headers=alice,
            json={"user_id": bob_user_id, "role": "viewer"},
        )
        assert response.status_code == 201
        assert response.json()["role"] == "viewer"
        response = await client.get(download, headers=bob)
        assert response.status_code == 200
        assert response.content == content
        # 8: Public download uses neither Alice's nor Bob's authentication.
        response = await client.post(
            f"/api/v1/drive/files/{file_id}/shared-links", headers=alice
        )
        assert response.status_code == 201
        public_url = response.json()["download_url"]
        assert public_url.startswith("/api/v1/drive/shared-links/")
        client.cookies.clear()
        response = await client.get(public_url)
        assert "authorization" not in response.request.headers
        assert response.status_code == 200
        assert response.content == content
        # 9: Delete and verify disappearance from the listing.
        response = await client.delete(f"/api/v1/drive/files/{file_id}", headers=alice)
        assert response.status_code == 204
        file_deleted = True
        response = await client.get(
            f"/api/v1/drive/folders/{folder_id}/contents", headers=alice
        )
        assert response.status_code == 200
        assert all(f["id"] != file_id for f in response.json()["files"])
        # 10: Both authenticated sharing and the public link stop working.
        assert (await client.get(download, headers=bob)).status_code == 403
        response = await client.get(public_url)
        assert "authorization" not in response.request.headers
        assert response.status_code == 404
        scenario_passed = True
    finally:
        # Delete uploaded bytes before the folder: folder deletion is soft only.
        try:
            if file_id is not None and not file_deleted:
                response = await client.delete(f"/api/v1/drive/files/{file_id}", headers=alice)
                assert response.status_code == 204, "Smoke file cleanup failed"
            response = await client.delete(f"/api/v1/drive/folders/{folder_id}", headers=alice)
            assert response.status_code == 204, "Smoke folder cleanup failed"
        except Exception:
            if scenario_passed:
                raise
            warnings.warn("Smoke cleanup failed; inspect resources created by this run", stacklevel=2)
