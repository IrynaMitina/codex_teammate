"""Release an immutable image to an existing ECS Express CloudFormation stack."""
import argparse
import copy
import json
import os
from pathlib import Path
import re
import subprocess

import boto3
from botocore.exceptions import ClientError


def build_image(ecr, repository, commit):
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ValueError("Expected a full Git commit SHA")
    name = repository.split("/", 1)[1]
    try:
        digest = ecr.describe_images(repositoryName=name, imageIds=[{"imageTag": commit}])["imageDetails"][0]["imageDigest"]
    except ecr.exceptions.ImageNotFoundException:
        registry = repository.split("/", 1)[0]
        password = subprocess.check_output(["aws", "ecr", "get-login-password"])
        subprocess.run(["docker", "login", "--username", "AWS", "--password-stdin", registry], input=password, check=True)
        subprocess.run(["docker", "build", "--platform", "linux/amd64", "-t", f"{repository}:{commit}", "."], check=True)
        subprocess.run(["docker", "push", f"{repository}:{commit}"], check=True)
        digest = ecr.describe_images(repositoryName=name, imageIds=[{"imageTag": commit}])["imageDetails"][0]["imageDigest"]
    Path("release.json").write_text(json.dumps({"image_uri": f"{repository}@{digest}", "commit": commit}) + "\n")


def read_release(path, repository, commit):
    release = json.loads(Path(path).read_text())
    if release.get("commit") != commit or not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ValueError("Release artifact does not match source commit")
    if not re.fullmatch(re.escape(repository) + r"@sha256:[a-f0-9]{64}", release.get("image_uri", "")):
        raise ValueError("Release image must be a digest in the configured repository")
    return release["image_uri"]


def stack_info(cfn, name, environment):
    stack = cfn.describe_stacks(StackName=name)["Stacks"][0]
    if stack["StackStatus"] not in {"CREATE_COMPLETE", "UPDATE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE"}:
        raise RuntimeError("Environment stack is not ready for deployment")
    parameters = {p["ParameterKey"]: p["ParameterValue"] for p in stack["Parameters"]}
    if parameters["Environment"] != environment:
        raise ValueError("Environment does not match stack")
    return stack, {o["OutputKey"]: o["OutputValue"] for o in stack["Outputs"]}


def service_info(ecs, outputs):
    result = ecs.describe_services(cluster=outputs["ClusterName"], services=[outputs["ServiceArn"]])
    if result.get("failures") or len(result.get("services", [])) != 1:
        raise RuntimeError("Cannot resolve the environment service")
    service = dict(result["services"][0])
    if not service.get("taskDefinition"):
        primary = [d for d in service.get("deployments", []) if d.get("status") == "PRIMARY"]
        if len(primary) != 1 or not primary[0].get("taskDefinition"):
            raise RuntimeError("Cannot resolve the primary service task definition")
        service["taskDefinition"] = primary[0]["taskDefinition"]
    return service


def migrate(ecs, outputs, image_uri, family):
    service = service_info(ecs, outputs)
    current = ecs.describe_task_definition(taskDefinition=service["taskDefinition"])["taskDefinition"]
    # Copy only registration inputs, excluding ECS-generated read-only metadata.
    allowed = ecs.meta.service_model.operation_model("RegisterTaskDefinition").input_shape.members
    candidate = {k: copy.deepcopy(v) for k, v in current.items() if k in allowed and k != "tags"}
    candidate["family"] = family
    primary = [c for c in candidate["containerDefinitions"] if any(p.get("containerPort") == 8000 for p in c.get("portMappings", []))]
    if len(primary) != 1:
        raise RuntimeError("Expected exactly one API container on port 8000")
    container = primary[0]
    container["image"] = image_uri
    revision = ecs.register_task_definition(**candidate)["taskDefinition"]["taskDefinitionArn"]
    task_arn = None
    try:
        result = ecs.run_task(
            cluster=outputs["ClusterName"], taskDefinition=revision, launchType="FARGATE", count=1,
            networkConfiguration={"awsvpcConfiguration": {
                "subnets": outputs["TaskSubnets"].split(","),
                "securityGroups": [outputs["TaskSecurityGroupId"]], "assignPublicIp": "ENABLED"}},
            overrides={"containerOverrides": [{"name": container["name"], "command": ["alembic", "upgrade", "head"]}]},
        )
        if result.get("failures") or len(result.get("tasks", [])) != 1:
            raise RuntimeError(f"Migration task did not start: {result.get('failures')}")
        task_arn = result["tasks"][0]["taskArn"]
        print(f"Migration task: {task_arn}", flush=True)
        ecs.get_waiter("tasks_stopped").wait(cluster=outputs["ClusterName"], tasks=[task_arn], WaiterConfig={"Delay": 10, "MaxAttempts": 90})
        result = ecs.describe_tasks(cluster=outputs["ClusterName"], tasks=[task_arn])
        if result.get("failures") or len(result.get("tasks", [])) != 1:
            raise RuntimeError("Cannot read migration result")
        task = result["tasks"][0]
        finished = [c for c in task.get("containers", []) if c["name"] == container["name"]]
        if len(finished) != 1 or finished[0].get("exitCode") != 0:
            raise RuntimeError(f"Migration failed; see task {task_arn} and logs {outputs['LogGroupName']}")
    except Exception:
        if task_arn:
            ecs.stop_task(cluster=outputs["ClusterName"], task=task_arn, reason="Migration failed or timed out")
        raise
    finally:
        ecs.deregister_task_definition(taskDefinition=revision)


def deploy(cfn, ecs, stack_name, environment, image_uri, role_arn):
    stack, outputs = stack_info(cfn, stack_name, environment)
    migrate(ecs, outputs, image_uri, f"drive-cd-{stack_name}-migration")
    parameters = [{"ParameterKey": p["ParameterKey"], **({"ParameterValue": image_uri} if p["ParameterKey"] == "ImageUri" else {"UsePreviousValue": True})} for p in stack["Parameters"]]
    try:
        cfn.update_stack(StackName=stack_name, UsePreviousTemplate=True, Parameters=parameters,
                         Capabilities=["CAPABILITY_IAM"], RoleARN=role_arn)
    except ClientError as error:
        if error.response["Error"]["Code"] != "ValidationError" or "No updates are to be performed" not in error.response["Error"]["Message"]:
            raise
    else:
        cfn.get_waiter("stack_update_complete").wait(StackName=stack_name, WaiterConfig={"Delay": 15, "MaxAttempts": 160})
    ecs.get_waiter("services_stable").wait(cluster=outputs["ClusterName"], services=[outputs["ServiceArn"]], WaiterConfig={"Delay": 15, "MaxAttempts": 80})
    service = service_info(ecs, outputs)
    task = ecs.describe_task_definition(taskDefinition=service["taskDefinition"])["taskDefinition"]
    primary = [c for c in task["containerDefinitions"] if any(p.get("containerPort") == 8000 for p in c.get("portMappings", []))]
    if len(primary) != 1 or primary[0]["image"] != image_uri or service["runningCount"] < 1:
        raise RuntimeError("Service did not stabilize on the requested image")
    print(f"Deployed {image_uri} to {environment}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["build", "deploy", "smoke"])
    args = parser.parse_args()
    if args.action == "build":
        build_image(boto3.client("ecr"), os.environ["REPOSITORY_URI"], os.environ["SOURCE_COMMIT"])
        return
    image_uri = read_release(Path(os.environ["CODEBUILD_SRC_DIR_ReleaseArtifact"]) / "release.json", os.environ["REPOSITORY_URI"], os.environ["SOURCE_COMMIT"])
    cfn = boto3.client("cloudformation")
    if args.action == "deploy":
        deploy(cfn, boto3.client("ecs"), os.environ["STACK_NAME"], os.environ["ENVIRONMENT"], image_uri, os.environ["CFN_ROLE_ARN"])
    else:
        stack, outputs = stack_info(cfn, os.environ["STACK_NAME"], "staging")
        if next(p["ParameterValue"] for p in stack["Parameters"] if p["ParameterKey"] == "ImageUri") != image_uri:
            raise RuntimeError("Staging no longer runs this release")
        endpoint = outputs["Endpoint"]
        os.environ["SMOKE_BASE_URL"] = endpoint if endpoint.startswith("https://") else "https://" + endpoint
        subprocess.run(["python", "-m", "pytest", "smoke/test_staging.py", "-q", "--tb=short"], check=True)


if __name__ == "__main__":
    main()
