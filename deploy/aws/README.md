# AWS 배포 코드와 기본 비활성 정책

이 저장소는 Docker Compose 로컬 실행과 GitHub Actions CI를 기본으로 합니다. 새 조직의 저장소에는 AWS 배포 역할, 저장소 변수 또는 자격 증명을 연결하지 않습니다. 과거 배포 대상의 리소스 식별자를 현재 배포 설정으로 사용하지 않습니다.

`appspec.yml`, `scripts/codedeploy/`, `deploy/aws/`는 향후 별도 환경에서 사용할 배포 구현과 설정 예시입니다. 저장소를 clone하거나 `main`에 push하는 것만으로 AWS 요청이 발생하지 않습니다. 이 정책은 별도 저장소 `review-catalog-platform-demo`의 Lambda 운영과는 독립적입니다.

## GitHub Actions 동작

`.github/workflows/ci-cd.yml`의 CI는 `main` push, pull request와 수동 실행에서 다음을 검증합니다.

1. Gitleaks로 커밋에 포함된 비밀정보를 검사합니다.
2. Backend Ruff·pytest, frontend lint·build를 실행합니다.
3. Compose 설정과 CodeDeploy shell hook의 문법·계약을 확인합니다.

AWS CD job은 아래 조건을 모두 만족해야 실행합니다.

- `workflow_dispatch` 수동 실행
- `main` 브랜치
- 수동 입력 `deploy_aws=true`
- 저장소 변수 `AWS_DEPLOY_ENABLED=true`

기본값에서는 CD가 **skipped**로 표시됩니다. AWS 설정이 없다는 이유로 CI가 실패하지 않습니다. 테스트에서 발견한 실제 오류는 CI 실패로 보고합니다.

## 향후 AWS 연결이 필요할 때

현재 이 절차는 수행하지 않습니다. 별도 환경을 준비한 뒤 다음 저장소 변수를 설정해야 합니다.

| 변수 | 내용 |
| --- | --- |
| `AWS_REGION` | 배포 리전 |
| `AWS_ROLE_ARN` | GitHub OIDC를 허용하는 배포 역할 |
| `ARTIFACT_BUCKET` | 비공개·버전 관리 S3 버킷 |
| `CODEDEPLOY_APPLICATION` | CodeDeploy application |
| `CODEDEPLOY_DEPLOYMENT_GROUP` | CodeDeploy deployment group |
| `CLOUDFRONT_DISTRIBUTION_ID` | 캐시를 갱신할 distribution |
| `HTTPS_ORIGIN` | 검증할 HTTPS 서비스 주소 |

`github-actions-role-trust.json`과 `github-actions-role-policy.json`의 자리표시자를 실제 환경 값으로 치환합니다. OIDC subject는 해당 조직의 subject 설정에 맞춰 검증해야 하며, 과거 저장소의 numeric ID를 재사용하지 않습니다. `production` GitHub Environment의 배포 보호 규칙을 설정하고, instance와 CodeDeploy agent·role, S3, CloudFront를 별도로 준비합니다.

활성화한 뒤에는 OIDC 단기 credential로 tracked source와 `REVISION`을 S3에 올리고 CodeDeploy를 실행합니다. `activate-release.sh`는 Git SHA별 디렉터리에서 Docker 이미지를 빌드하고, 정상 검증 후 current symlink를 전환합니다. 마지막으로 CloudFront cache를 무효화하고 HTTPS endpoint를 검증합니다.

모델 snapshot은 Git이나 Actions artifact에 넣지 않습니다. 호스트의 `/opt/review-catalog-platform/shared/models`에 현재 taxonomy manifest와 일치하는 모델을 준비해야 합니다. `.env`와 인증정보는 배포 번들에 포함하지 않습니다.

## 로컬 검증

```bash
docker compose config --quiet
bash -n deploy/aws/activate-release.sh deploy/aws/user-data.sh scripts/codedeploy/*.sh
```

최초 초기화 입력은 `data/migration`, 신규 리뷰 파일 입력은 `data/ingestion`입니다. Docker에서는 읽기 전용으로 mount하며 운영 출력은 `catalog_data` named volume에 기록합니다. 데이터 폴더 이동이나 저장소 이관을 이유로 `docker compose down -v`를 실행하지 않습니다.
