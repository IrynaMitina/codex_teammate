from smoke.scenario import run_drive_scenario


async def test_drive7_scenario(client, temp_storage):
    await run_drive_scenario(
        client, alice_email="alice@example.com", alice_password="alice123",
        bob_email="bob@example.com", bob_password="bob123", bob_user_id=2,
    )
