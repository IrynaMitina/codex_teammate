# Architecture Design

## Overview
The backend API is deployed as a containerized application in AWS using **ECS Express Mode**.

Application data is stored in **RDS PostgreSQL**, while uploaded files are stored in **S3**.

The architecture starts small and simple, while allowing the infrastructure to scale as the product grows.

## AWS Services

To run the backend API in AWS:

| Service | Purpose | Initial Setup |
|---|---|---|
| ECS Express Mode | Run the containerized backend API | Small Fargate tasks with load balancing and auto scaling |
| ECR | Store Docker images | Shared repository for staging and production |
| S3 | Store uploaded files | Separate buckets for staging and production |
| RDS PostgreSQL | Managed application database | Small Single-AZ instance, automated backups |
| Secrets Manager | Store database credentials and JWT secret | Inject secrets into the container |
| CloudWatch | Application logs and monitoring | Short log retention |

**Reasoning — Why was this architecture chosen?**

- **Simple provisioning** — ECS Express Mode configures Fargate, load balancing, and scaling.
- **Start small** — use minimal resources for the first customers.
- **Grow naturally** — scale infrastructure as usage grows.


## Environments

| Environment | Purpose | Resources |
|---|---|---|
| **Production** | Serve end users | ECS Express Mode, S3, RDS PostgreSQL, Secrets Manager |
| **Staging** | Pre-release validation | Same architecture as production, with separate resources |
| **Test** | Run unit tests as part of CI pipeline | Temporary SQLite database, temporary local storage |
| **Local** | Local development | SQLite or PostgreSQL in Docker, local storage |

> **Important:** Production and staging are fully isolated. They use separate databases, S3 buckets, secrets, and compute resources.

## Automation
Sketch for CI/CD pipeline.
Pipeline will have 2 parts: first - in GitHub, second - in AWS.

### CI
- Creating or updating a pull request to `main` runs unit tests automatically.
- Test coverage must be at least **80%**.
- Failed tests or insufficient coverage block the merge.

### CD
- Merge to `main` triggers deployment to **staging**.
- After deployment, smoke tests run automatically against staging.
- Failed smoke tests stop the release.
- Deployment to **production** requires manual approval.
- Merge to `main` triggers deployment to **staging**.
- After deployment, smoke tests run automatically against staging.
- Failed smoke tests stop the release.
- Deployment to **production** requires manual approval.
- The **same container image** deployed and tested in staging is promoted to production after manual approval.



## Key Decisions
- Containerized application
- ECS Express Mode for simple provisioning and future scaling
- PostgreSQL for staging/production
- S3 for persistent file storage
- Staging and production are isolated
- Same container image is promoted from staging to production


## Future Evolution
The application remains containerized, allowing it to migrate from **ECS to EKS** if future scale or operational requirements justify Kubernetes.