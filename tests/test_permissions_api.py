import pytest

from app.core.security import create_access_token


@pytest.fixture
def alice_headers():
    return {"Authorization": f"Bearer {create_access_token('1')}"}


@pytest.fixture
def bob_headers():
    return {"Authorization": f"Bearer {create_access_token('2')}"}


async def test_permission_upgrade_and_revocation(client, alice_headers, bob_headers):
    response = await client.post("/api/v1/drive/folders", headers=alice_headers,
                                 json={"name": "shared folder"})
    assert response.status_code == 201
    folder_id = response.json()["id"]
    contents = f"/api/v1/drive/folders/{folder_id}/contents"
    share = f"/api/v1/drive/folder/{folder_id}/share"
    permissions = f"/api/v1/drive/folder/{folder_id}/permissions"
    assert (await client.get(contents, headers=bob_headers)).status_code == 403
    response = await client.post(share, headers=alice_headers,
                                 json={"user_id": 2, "role": "viewer"})
    assert response.status_code == 201
    permission_id = response.json()["id"]
    assert (await client.get(contents, headers=bob_headers)).status_code == 200
    child = {"name": "child", "parent_id": folder_id}
    assert (await client.post("/api/v1/drive/folders", headers=bob_headers,
                              json=child)).status_code == 403
    assert (await client.get(permissions, headers=bob_headers)).status_code == 403
    assert (await client.delete(f"/api/v1/drive/permissions/{permission_id}",
                                headers=bob_headers)).status_code == 403
    response = await client.post(share, headers=alice_headers,
                                 json={"user_id": 2, "role": "editor"})
    assert response.status_code == 201
    assert response.json()["id"] == permission_id
    response = await client.get(permissions, headers=alice_headers)
    assert response.status_code == 200
    assert [(p["user_id"], p["role"]) for p in response.json()] == [(2, "editor")]
    response = await client.post("/api/v1/drive/folders", headers=bob_headers, json=child)
    assert response.status_code == 201
    child_id = response.json()["id"]
    response = await client.get(contents, headers=alice_headers)
    assert [f["id"] for f in response.json()["folders"]] == [child_id]
    assert (await client.delete(f"/api/v1/drive/permissions/{permission_id}",
                                headers=alice_headers)).status_code == 204
    assert (await client.get(contents, headers=bob_headers)).status_code == 403
    assert (await client.get(permissions, headers=alice_headers)).json() == []
    assert (await client.delete(f"/api/v1/drive/permissions/{permission_id}",
                                headers=alice_headers)).status_code == 404
    assert (await client.delete(f"/api/v1/drive/folders/{folder_id}",
                                headers=alice_headers)).status_code == 204
    # Parent deletion also hides its immediate children, including Bob's.
    assert (await client.get(f"/api/v1/drive/folders/{child_id}/contents",
                             headers=bob_headers)).status_code == 403


@pytest.mark.parametrize("target,role,status", [(1, "viewer", 400),
                                                  (99999, "viewer", 404),
                                                  (2, "admin", 400)])
async def test_invalid_sharing(client, alice_headers, target, role, status):
    response = await client.post("/api/v1/drive/folders", headers=alice_headers,
                                 json={"name": "private"})
    folder_id = response.json()["id"]
    response = await client.post(f"/api/v1/drive/folder/{folder_id}/share",
                                 headers=alice_headers, json={"user_id": target, "role": role})
    assert response.status_code == status
    assert (await client.get(f"/api/v1/drive/folder/{folder_id}/permissions",
                             headers=alice_headers)).json() == []


@pytest.mark.parametrize("token", [None, "invalid-token", create_access_token("99999")])
async def test_folder_requires_valid_existing_user(client, token):
    headers = {} if token is None else {"Authorization": f"Bearer {token}"}
    response = await client.post("/api/v1/drive/folders", headers=headers,
                                 json={"name": "unauthorized"})
    assert response.status_code == 401
