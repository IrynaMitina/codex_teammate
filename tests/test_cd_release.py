"""Offline checks for deployment failure gates; no AWS credentials are used."""
import copy
import json
from unittest.mock import Mock

import boto3
from botocore.exceptions import ClientError, WaiterError
import pytest

from infra.cd import release

REPOSITORY = "123456789012.dkr.ecr.eu-central-1.amazonaws.com/drive"
COMMIT = "a" * 40
IMAGE = REPOSITORY + "@sha256:" + "b" * 64
OUTPUTS = {"ClusterName": "staging", "ServiceArn": "service", "TaskSubnets": "subnet-a,subnet-b", "TaskSecurityGroupId": "sg-task", "LogGroupName": "logs"}
TASK = {"family": "api", "taskDefinitionArn": "old", "revision": 1, "status": "ACTIVE", "executionRoleArn": "execution", "taskRoleArn": "task", "networkMode": "awsvpc", "requiresCompatibilities": ["FARGATE"], "cpu": "256", "memory": "512", "containerDefinitions": [{"name": "Main", "image": IMAGE, "portMappings": [{"containerPort": 8000}], "secrets": [{"name": "DB_PASSWORD", "valueFrom": "secret"}], "environment": [{"name": "APP_ENV", "value": "staging"}]}]}


@pytest.fixture
def ecs():
    client = Mock()
    # Use the actual boto3 input schema without making any network calls.
    model_client = boto3.client("ecs", region_name="eu-central-1", aws_access_key_id="test", aws_secret_access_key="test")
    client.meta.service_model = model_client.meta.service_model
    client.describe_services.return_value = {"services": [{"taskDefinition": "old", "runningCount": 1}]}
    client.describe_task_definition.return_value = {"taskDefinition": copy.deepcopy(TASK)}
    client.register_task_definition.return_value = {"taskDefinition": {"taskDefinitionArn": "migration-revision"}}
    client.run_task.return_value = {"tasks": [{"taskArn": "migration-task"}]}
    client.describe_tasks.return_value = {"tasks": [{"containers": [{"name": "Main", "exitCode": 0}]}]}
    return client


@pytest.fixture
def cfn():
    client = Mock()
    client.describe_stacks.return_value = {"Stacks": [{"StackStatus": "UPDATE_COMPLETE", "Parameters": [{"ParameterKey": "Environment", "ParameterValue": "staging"}, {"ParameterKey": "ImageUri", "ParameterValue": "old-image"}, {"ParameterKey": "DatabaseInstanceClass", "ParameterValue": "db.t4g.micro"}], "Outputs": [{"OutputKey": k, "OutputValue": v} for k, v in OUTPUTS.items()]}]}
    return client


@pytest.mark.parametrize("change", [{"commit": "c" * 40}, {"image_uri": REPOSITORY + ":latest"}, {"image_uri": "untrusted@sha256:" + "b" * 64}])
def test_reject_untrusted_release(tmp_path, change):
    artifact = tmp_path / "release.json"
    artifact.write_text(json.dumps({"commit": COMMIT, "image_uri": IMAGE, **change}))
    with pytest.raises(ValueError):
        release.read_release(artifact, REPOSITORY, COMMIT)


def test_accept_digest_release(tmp_path):
    artifact = tmp_path / "release.json"
    artifact.write_text(json.dumps({"commit": COMMIT, "image_uri": IMAGE}))
    assert release.read_release(artifact, REPOSITORY, COMMIT) == IMAGE


def test_build_retry_reuses_immutable_image(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ecr = Mock()
    ecr.describe_images.return_value = {"imageDetails": [{"imageDigest": "sha256:" + "b" * 64}]}
    run = Mock()
    monkeypatch.setattr(release.subprocess, "run", run)
    release.build_image(ecr, REPOSITORY, COMMIT)
    run.assert_not_called()
    assert release.read_release("release.json", REPOSITORY, COMMIT) == IMAGE


def test_migrate_preserves_secrets_and_network_but_uses_candidate(ecs):
    candidate = REPOSITORY + "@sha256:" + "c" * 64
    release.migrate(ecs, OUTPUTS, candidate, "drive-cd-staging-migration")
    definition = ecs.register_task_definition.call_args.kwargs
    assert definition["family"] == "drive-cd-staging-migration"
    assert "taskDefinitionArn" not in definition
    assert definition["containerDefinitions"][0]["image"] == candidate
    assert definition["containerDefinitions"][0]["secrets"] == TASK["containerDefinitions"][0]["secrets"]
    assert ecs.describe_task_definition.return_value["taskDefinition"] == TASK
    task = ecs.run_task.call_args.kwargs
    assert task["taskDefinition"] == "migration-revision"
    assert task["overrides"]["containerOverrides"][0]["command"] == ["alembic", "upgrade", "head"]
    assert task["networkConfiguration"]["awsvpcConfiguration"]["securityGroups"] == ["sg-task"]
    ecs.deregister_task_definition.assert_called_once_with(taskDefinition="migration-revision")


@pytest.mark.parametrize("containers", [[{"name": "Main", "exitCode": 1}], [{"name": "Main"}], []])
def test_failed_migration_never_updates_stack(cfn, ecs, containers):
    ecs.describe_tasks.return_value = {"tasks": [{"containers": containers}]}
    with pytest.raises(RuntimeError, match="Migration failed"):
        release.deploy(cfn, ecs, "drive-staging", "staging", IMAGE, "cfn-role")
    cfn.update_stack.assert_not_called()
    ecs.deregister_task_definition.assert_called_once()


def test_task_launch_failure_stops_deployment(cfn, ecs):
    ecs.run_task.return_value = {"failures": [{"reason": "RESOURCE:MEMORY"}], "tasks": []}
    with pytest.raises(RuntimeError, match="did not start"):
        release.deploy(cfn, ecs, "drive-staging", "staging", IMAGE, "cfn-role")
    cfn.update_stack.assert_not_called()
    ecs.deregister_task_definition.assert_called_once()


def test_migration_timeout_stops_task(cfn, ecs):
    ecs.get_waiter.return_value.wait.side_effect = WaiterError(name="tasks_stopped", reason="timeout", last_response={})
    with pytest.raises(WaiterError):
        release.deploy(cfn, ecs, "drive-staging", "staging", IMAGE, "cfn-role")
    ecs.stop_task.assert_called_once()
    cfn.update_stack.assert_not_called()


def test_environment_mismatch_prevents_any_task(cfn, ecs):
    with pytest.raises(ValueError, match="Environment"):
        release.deploy(cfn, ecs, "drive-staging", "production", IMAGE, "cfn-role")
    ecs.run_task.assert_not_called()


def test_success_migrates_before_stack_update_and_preserves_parameters(cfn, ecs):
    calls = Mock()
    calls.attach_mock(ecs, "ecs")
    calls.attach_mock(cfn, "cfn")
    release.deploy(cfn, ecs, "drive-staging", "staging", IMAGE, "cfn-role")
    names = [call[0] for call in calls.mock_calls]
    assert names.index("ecs.describe_tasks") < names.index("cfn.update_stack")
    request = cfn.update_stack.call_args.kwargs
    assert request["UsePreviousTemplate"] is True
    assert request["RoleARN"] == "cfn-role"
    assert request["Parameters"] == [{"ParameterKey": "Environment", "UsePreviousValue": True}, {"ParameterKey": "ImageUri", "ParameterValue": IMAGE}, {"ParameterKey": "DatabaseInstanceClass", "UsePreviousValue": True}]


def test_cloudformation_failure_is_not_swallowed(cfn, ecs):
    cfn.update_stack.side_effect = ClientError({"Error": {"Code": "AccessDenied", "Message": "denied"}}, "UpdateStack")
    with pytest.raises(ClientError):
        release.deploy(cfn, ecs, "drive-staging", "staging", IMAGE, "cfn-role")


def test_noop_retry_still_checks_service(cfn, ecs):
    cfn.update_stack.side_effect = ClientError({"Error": {"Code": "ValidationError", "Message": "No updates are to be performed."}}, "UpdateStack")
    release.deploy(cfn, ecs, "drive-staging", "staging", IMAGE, "cfn-role")
    cfn.get_waiter.assert_not_called()
    assert ecs.describe_services.call_count == 2


def test_stable_but_rolled_back_image_fails(cfn, ecs):
    ecs.describe_task_definition.return_value["taskDefinition"]["containerDefinitions"][0]["image"] = "old-image"
    with pytest.raises(RuntimeError, match="requested image"):
        release.deploy(cfn, ecs, "drive-staging", "staging", IMAGE, "cfn-role")


def test_express_service_uses_primary_deployment_task_definition(cfn, ecs):
    ecs.describe_services.return_value = {"services": [{"runningCount": 1, "deployments": [
        {"status": "ACTIVE", "taskDefinition": "previous"},
        {"status": "PRIMARY", "taskDefinition": "current"},
    ]}]}
    release.deploy(cfn, ecs, "drive-staging", "staging", IMAGE, "cfn-role")
    assert all(call.kwargs["taskDefinition"] == "current" for call in ecs.describe_task_definition.call_args_list)


def test_missing_primary_task_definition_stops_deployment(cfn, ecs):
    ecs.describe_services.return_value = {"services": [{"deployments": []}]}
    with pytest.raises(RuntimeError, match="primary service task definition"):
        release.deploy(cfn, ecs, "drive-staging", "staging", IMAGE, "cfn-role")
    ecs.run_task.assert_not_called()
    cfn.update_stack.assert_not_called()
