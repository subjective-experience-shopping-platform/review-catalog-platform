# 단일 EC2 배포 가이드

새 조직에서는 AWS에 연결하지 않습니다. 아래 내용은 향후 배포를 위한 참고 설계입니다. AWS 설정과 수동 활성화 방법은 [`../aws/README.md`](../aws/README.md)를 기준으로 한다. 이 문서는 현재 단일 EC2 topology와 별도 데이터 volume을 추가할 때의 확장 방향을 기록한다.

## 권장 topology

- Amazon Linux 2023 ARM64, 현재 데모 기준 2 vCPU / 8GB RAM
- catalog snapshot과 PostgreSQL volume을 위한 별도 암호화 gp3 EBS
- CloudFront 기본 도메인과 인증서로 viewer HTTPS를 종료하며 HTTP 요청은 HTTPS로 redirect한다.
- public subnet의 EC2 TCP 80은 AWS 관리형 CloudFront origin-facing prefix list에서만 허용하고, public IP 직접 접속은 차단한다.
- Airflow `8080`, FastAPI `8000`, PostgreSQL `5432` public ingress 금지
- SSH key 대신 SSM Session Manager 사용
- EC2 IAM Role에는 ECR pull, CloudWatch Logs, 필요한 Secrets Manager read만 최소 권한 부여

단일 호스트 장애 시 demo 전체가 중단되므로 production HA 구성은 아니다. 중요한 release는 주기적으로 S3에 object-lock 또는 versioning과 함께 백업한다.

## 설치

1. Docker Engine과 Compose v2를 설치한다.
2. repository를 `/opt/review-catalog-platform`에 배치한다.
3. 장기 운영으로 전환할 때 `/opt/review-catalog-data`에 별도 EBS를 mount하고 Docker named volume 또는 bind mount target으로 사용한다.
4. 현재는 EC2-local root-only `.env`를 사용한다. 장기 운영으로 전환할 때 Secrets Manager/SSM Parameter Store에서 materialize한다.
5. 다음을 실행한다.

```bash
cd /opt/review-catalog-platform
docker compose pull
docker compose build
docker compose up -d
docker compose ps
```

6. health check는 `/api/health`를 사용한다.
7. 최초 실제 Parquet migration을 FastAPI `POST /api/pipeline-runs`로 실행하고 1,609건 전체 이관을 확인한다.

## 배포 순서

schema/코드 호환성을 확인한 뒤 image를 build하고, `airflow-init`, `airflow-pool-init`, Airflow services, API, frontend 순으로 올라오게 한다. 새 container가 기존 immutable release를 읽을 수 있는지 먼저 확인한 후 ingestion을 허용한다.

## 백업

- PostgreSQL: `pg_dump`를 암호화 S3 prefix로 전송
- catalog: Docker의 `catalog_data` named volume에 있는 `/data/catalog/releases/`를 백업한다. 로컬 직접 실행은 `data/runtime/releases/`를 사용한다. `work/`, `release-staging/`은 실행·복구 참조를 확인한 뒤 정리한다.
- 복구 시험에서 manifest의 SHA-256과 snapshot read-only open을 반드시 확인

## GitHub Actions와 CodeDeploy

GitHub Actions는 기본적으로 CI만 실행합니다. AWS CD는 수동 `deploy_aws` 입력과 `AWS_DEPLOY_ENABLED=true` 및 별도 배포 설정이 모두 준비되어야 실행됩니다. 활성화하지 않은 CD job은 skipped로 종료되며 CI 실패로 처리되지 않습니다. 설정 방법은 [`../aws/README.md`](../aws/README.md)를 따릅니다.

새 호스트는 배포 전에 [모델 자산 안내](../../AGENTS.md#모델-자산)에 따라 현재 SBERT snapshot을 shared/models에 준비한다. 기존 카탈로그에서 정리된 bootstrap으로 전환하는 절차는 [개발·운영 지침](../../AGENTS.md)를 따른다.

배포 번들은 `data/migration`과 `data/ingestion`을 포함해야 한다. Docker image에는 입력 데이터를 복사하지 않고 각 디렉터리를 Airflow에 읽기 전용으로 mount한다. 운영 출력은 기존 `catalog_data` volume에 기록하므로 입력 폴더 이동을 위해 `docker compose down -v`를 실행하지 않는다.
