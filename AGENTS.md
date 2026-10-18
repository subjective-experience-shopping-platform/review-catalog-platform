# review-catalog-platform 작업 지침

이 파일은 이 저장소를 수정하는 Coding AI와 개발자를 위한 구현·검증·운영 기준이다. 사용자 요청의 범위를 먼저 확인하고 관련 코드와 테스트를 함께 읽는다. 사용자에게 표시하는 실험 설명은 `backend/src/review_catalog/content/experiment.md`에서 관리한다.

## 작업을 시작할 때

- 먼저 `git status --short`로 기존 변경을 확인한다. 이번 작업과 무관한 수정·삭제·미추적 파일을 덮어쓰거나 복원하지 않는다.
- `README.md`에서 제품 목적과 사용자 흐름을 파악한 뒤 아래 코드 안내에서 변경할 영역을 찾는다.
- 문서의 설명, 코드의 동작, 실행으로 검증한 사실을 구분한다. 불일치는 관련 테스트와 실제 호출 경로로 확인한 뒤 함께 수정한다.
- 요청된 변경을 현재 구조 안에서 해결한다. 실험 코드 사본, 구버전 입력 호환 분기, 불필요한 프레임워크를 추가하지 않는다.
- 다른 프로젝트의 데이터와 모델은 원본으로 취급한다. 이 저장소의 복사본을 수정하는 작업 때문에 원본 프로젝트를 변경하지 않는다.
- 커밋·push·배포·원격 데이터 변경은 사용자가 요청한 작업 범위에 따라 수행한다. 로컬 검증을 위해 운영 서비스에 테스트 리뷰를 제출하지 않는다.

## 코드 안내와 책임 경계

| 영역 | 위치 | 책임 |
| --- | --- | --- |
| 실행 설정 | `backend/src/review_catalog/settings.py` | `REVIEW_CATALOG_` 환경변수, 경로, 모델/provider 설정 |
| HTTP API | `backend/src/review_catalog/api/` | 입력 검증, Airflow 실행 요청, 발행 결과 조회 |
| 운영 metadata | `backend/src/review_catalog/db/` | PostgreSQL 모델, 세션, schema 초기화 |
| 신규 리뷰 파이프라인 | `backend/src/review_catalog/pipeline/stages.py` | 입력 준비, 중복 제거, 추출·검증·매핑, delta 준비 |
| 카탈로그 저장 | `backend/src/review_catalog/pipeline/catalog_store.py` | DuckDB schema, bootstrap, delta commit, taxonomy 설치 |
| 추출 | `backend/src/review_catalog/extraction/` | Opinion Unit 계약·프롬프트, Codex CLI/OpenAI provider |
| 정규화 | `backend/src/review_catalog/normalization/` | exact mapping, candidate 추론, 전체 군집화, 설정·manifest 검증 |
| 재군집화 파이프라인 | `backend/src/review_catalog/pipeline/reclustering.py` | snapshot capture, bundle 생성, 단일 writer commit |
| 버전·발행 | `backend/src/review_catalog/services/versions.py`, `backend/src/review_catalog/services/release.py` | component registry, 보고서 생성, 원자적 발행·복구 |
| 분석·보고서 | `backend/src/review_catalog/reporting/` | 리뷰 근거 집계, 정적 분석·동적 제안서 JSON/Markdown |
| 스케줄·직렬화 | `airflow/dags/`, `scripts/init_airflow_pool.py` | DAG 의존성, 수동 재군집화, writer pool |
| 사용자 화면 | `frontend/src/pages/`, `frontend/src/lib/api.ts` | 설명 탭, 상품 보고서, 리뷰 데모와 API 계약 |
| 배포 | `docker/`, `docker-compose.yml`, `scripts/codedeploy/`, `deploy/`, `.github/workflows/ci-cd.yml` | 이미지·볼륨·권한·CI/CD |
| 검증 | `backend/tests/` | 데이터 무결성, 매핑, 보고서, 파이프라인, 패키징·경로 계약 |

FastAPI는 요청을 접수하고 Airflow에 처리를 위임한다. HTTP 요청 안에서 카탈로그 추출·재군집화를 직접 실행하지 않는다. 보고서와 최종 release 발행은 FastAPI의 release finalizer가 담당한다.

## 데이터 모델과 불변조건

- PostgreSQL의 애플리케이션 테이블은 `component_versions`, `pipeline_runs`, `demo_submissions`, `demo_reviews`, `catalog_releases`, `report_artifacts`다. Airflow metadata DB는 별개다.
- DuckDB의 `products`, `reviews`, `opinion_units`는 상품·원문·추출/매핑 결과다. taxonomy/mapping/cluster 테이블은 버전별 정규화 자료다.
- `source_artifacts`, `migration_manifests`, `catalog_commits`, `taxonomy_rebuilds`는 출처·이관·commit·재군집화 기록이다. 실제 열과 제약은 위 코드 안내의 DB 모델과 카탈로그 저장 schema를 기준으로 확인한다.
- 영속 카탈로그 쓰기는 Airflow의 `commit_catalog_delta` 또는 `commit_taxonomy_rebuild`에서만 수행한다. `writer_identity="airflow"`, `duckdb_writer_pool`의 `pool_slots=1`, 파일 lock을 유지한다.
- API와 보고서 생성기는 DuckDB에 `read_only=True`로 연결한다. 운영 metadata를 갱신하는 PostgreSQL transaction과 혼동하지 않는다.
- 이미 발행한 snapshot·보고서·component version을 덮어쓰지 않는다. 바뀐 코드·설정·모델·데이터에는 새로운 식별자를 부여한다.
- 새 릴리스는 snapshot과 전체 보고서·manifest/hash를 준비한 뒤 디렉터리 rename으로 공개하고 PostgreSQL의 current pointer를 전환한다. 파일 rename과 metadata 등록 사이의 장애를 재시도로 복구할 수 있어야 한다.
- 정적 보고서는 전체 상품에 대해 생성한다. 동적 제안서는 `demo_review_id`가 있는 UI 제출 리뷰에 대해서만 생성한다.

## 추출·매핑·재군집화 계약

- Opinion Unit은 `raw_aspect`, `raw_status`, `excerpt`, `opinion`, `sentiment`를 보존한다. `excerpt`는 리뷰 원문에 연속해서 존재해야 하며 strict schema와 grounding 검증을 우회하지 않는다.
- 기존 raw 표현은 활성 mapping table의 exact lookup을 우선한다. 미등록 표현은 `candidate`로 기록하며 canonical 값을 임의로 확정하지 않는다. 후보의 제안 값·거리 진단과 확정 매핑을 구분한다.
- 제외 규칙은 normalization 설정에서 읽고 `excluded_taxonomy` 결과를 보존한다. 제외된 원본을 삭제하거나 canonical 집계에 포함하지 않는다.
- status는 해당 `aspect_cluster_id` 경계 안에서 처리한다. cosine/complete linkage, threshold, 반대 상태·명시적 부정 제약과 대표명 정책을 함께 유지한다.
- `normalization/taxonomy.py`의 설정 fingerprint·manifest 검증을 유지한다. 설정을 줄이거나 바꾸면서 해시 검증만 끄지 않는다.
- `Catalog_ingestion`은 매일 서울 시간 00시에 실행되고 API에서도 trigger할 수 있다. 초기 bootstrap 이후에는 증분 처리한다.
- 파일 inbox 리뷰는 content hash로 중복 제거한다. UI 리뷰는 제출 이벤트이며 같은 텍스트가 기존 카탈로그에 있어도 입력별 결과를 제공해야 한다.
- `Catalog_reclustering`은 수동 실행 전용이다. 시작 시점 snapshot을 고정하고 그 자료만 군집화한다. 실행 중 새로 들어온 Opinion Unit은 commit에서 보존하고 다음 재군집화에 반영한다.
- 재군집화의 mapping/embedding component pointer는 새 release 발행 transaction에서 활성화한다. bundle 생성만으로 활성 버전을 바꾸지 않는다.
- 후보 수 threshold는 재구축 권고 기록이다. 임의로 자동 재군집화 trigger로 변경하지 않는다.

## 데이터 폴더와 저장 경계

```text
data/
├── migration/source/
│   ├── data/                         # dataset.parquet, opinion_units.parquet
│   └── taxonomy/2026-10-05_142933/    # D 매핑·군집 Parquet 5개
├── ingestion/inbox_reviews.json      # 신규 리뷰 파일 입력
└── runtime/
    ├── work/
    ├── release-staging/
    ├── releases/
    └── locks/
```

- 로컬 직접 실행의 기본 출력은 `data/runtime`이다. `get_settings()`는 출력 디렉터리만 생성하며 입력 Parquet이나 inbox를 자동 생성하지 않는다.
- Docker는 `data/migration`, `data/ingestion`을 Airflow의 `/opt/project/data/migration`, `/opt/project/data/ingestion`에 각각 읽기 전용 bind mount한다.
- Docker 출력은 기존 `catalog_data` named volume의 `/data/catalog`에 저장한다. 호스트의 `data/runtime`은 이 volume과 별개다. volume key·Compose project 이름·컨테이너 경로를 바꾸면 기존 metadata의 절대 경로 참조도 검토한다.
- Git 추적·배포 대상은 초기화 입력과 기본 inbox다. `data/runtime`과 그 밖의 임의 데이터는 제외한다. `.gitignore`에서 상위 `data` 전체를 제외해 입력까지 누락시키지 않는다.
- Docker build context에서는 `data` 전체를 제외한다. CodeDeploy source bundle에 필요한 입력은 Git에 포함하고 실행 시 bind mount로 제공한다.
- 기본 inbox는 빈 JSON 배열이다. 항목의 필수 필드는 `source_review_id`, `product_id`, `product_name`, `review_text`이고 `source`, `category`는 선택이다. 파일을 자동 수집하거나 처리 완료 행을 삭제하는 기능은 없다.
- 웹 데모 입력은 PostgreSQL의 `demo_reviews`에서 읽으며 inbox를 거치지 않는다. 실제 운영 리뷰·실행 산출물을 테스트 fixture 대신 사용하지 않는다.

## 초기 migration

- 현재 기준 실험은 `2026-10-05_142933`이다. 실제 수량·파일 hash·prompt/model identity는 `config/taxonomy/2026-10-05_142933.json`과 운영 입력에서 확인한다.
- bootstrap 입력은 리뷰·Opinion Unit Parquet 2개와 D assignment/aspect-node/aspect-cluster/status-node/status-cluster Parquet 5개다. 정확한 7개 파일 inventory, SHA-256, 행 수를 검증한다.
- 전체 bootstrap을 원자적으로 처리하며 부분 이관을 거부한다. 같은 bootstrap의 재실행은 이관 기록으로 구분하고 다른 데이터셋으로 초기화된 카탈로그에 새 bootstrap을 덧붙이지 않는다.
- source cluster ID·대표명·매핑·거리를 보존한다. 운영용 node/centroid/canonical embedding과 거리 진단을 추가한 taxonomy를 사용한다.
- 샘플, A/B/C 비교 결과, 직접 속성 추출 결과, 원 실험 코드 사본은 중복 보관하지 않는다. 원본은 `semantic-review-extraction-experiment`에서 관리한다.
- 원 실험은 임시 LLM 응답을 보존하지 않았다. bootstrap의 `extraction_response_sha256`은 검증된 `opinion_units.parquet` 해시이며 원시 응답 해시를 의미하지 않는다. 신규 리뷰의 응답 해시와 구분한다.
- 데이터셋·스키마 전환이 필요하면 기존 서비스를 백업·유지하고 별도 카탈로그를 초기화·검증한 뒤 전환한다. 기존 row나 manifest hash를 수정해 검증을 통과시키지 않는다. 입력 폴더만 옮기는 작업은 데이터셋 전환과 구분한다.

## 모델 자산

- 모델은 `snunlp/KR-SBERT-Medium-extended-klueNLItriplet_PARpair_QApair-klueSTS`의 고정 snapshot을 사용한다. 현재 revision은 `76aeef8c39c64fc92c7de7d4e926285ce1c43c9f`이며 weights SHA-256은 활성 taxonomy manifest와 대조한다.
- 로컬 모델 위치는 `models/snunlp--KR-SBERT-Medium-extended-klueNLItriplet_PARpair_QApair-klueSTS/`다. `semantic-review-extraction-experiment/models`에서 복사한 snapshot의 `snapshot_manifest.json`을 확인한다.
- 약 447 MiB의 `model.safetensors`와 tokenizer, pooling, model configuration을 함께 준비한다. weight 하나만 복사해서 전체 snapshot이 준비됐다고 판단하지 않는다.
- 모델 binary와 Hugging Face download cache는 Git·GitHub Actions artifact에 넣지 않는다. immutable 모델 자산과 실행별 논리 component version을 구분한다.
- EC2는 배포 전에 `/opt/review-catalog-platform/shared/models`에 검증된 snapshot을 준비하고 컨테이너가 읽을 수 있게 한다. CodeDeploy는 각 release의 `models`를 이 위치에 연결한다.
- shared 모델이 없으면 배포가 명시적으로 실패한다. 이전 application release 디렉터리에서 복사하거나 다른 revision을 자동 다운로드하는 fallback을 추가하지 않는다.
- 수동 재군집화는 같은 weights를 재사용해 표현을 다시 인코딩하고 실행별 `embedding_model_manifest.json`을 만든다. 가중치를 재학습하거나 실행마다 중복 복사하지 않는다.

## 사용자 화면·보고서·콘텐츠

- 설명 화면의 탭은 Overview, Experiment, Release다. 상품 보고서와 리뷰 데모의 로딩·오류·빈 결과·polling 동작을 유지한다.
- Experiment 본문은 backend 패키지의 `content/experiment.md`다. `Settings.experiment_markdown_path`의 기본값은 설치된 패키지 기준 경로이며 wheel과 Docker 이미지에 함께 포함된다.
- 앱에서 제공하는 실험 그림은 `frontend/public/experiment/`에 둔다. 해당 그림을 참조할 때 `/experiment/...` URL을 사용한다. 본문을 수정할 때 로컬 그림과 외부 이미지 URL의 실제 접근도 함께 확인한다.
- `/api/about/experiment`의 `markdown`, `source_url` 응답 형태를 유지한다. 현재 로컬 콘텐츠의 `source_url`은 null이다. Overview와 Release는 공개 GitHub README를 읽으며 네트워크 실패 시 기존 오류 응답을 유지한다.
- 이 `AGENTS.md`를 사용자 화면이나 추출 모델의 프롬프트에 넣지 않는다. 이 파일은 저장소 작업 지침이다.
- 보고서는 LLM 없이 카탈로그 분석 코드로 생성한다. 근거가 없는 상태를 부정 평가나 객관적 성능 보장으로 바꾸지 않는다. 후보·제외 결과도 확정된 비교 근거로 사용하지 않는다.
- JSON schema, 보고서 ID, generator version과 Markdown 표시 형식을 함께 확인한다. 현재 정적 schema는 `2.0.0`, 동적 schema는 `3.0.0`이며 실제 상수는 `reporting/static.py`, `dynamic.py`가 기준이다.
- `report_generator` identity는 보고서 코드의 hash와 application/deployment version을 포함한다. 코드가 바뀌었는데 기존 immutable version을 재사용하지 않는다.

## 변경 시 함께 확인할 항목

| 변경 | 함께 확인할 항목 |
| --- | --- |
| 경로·데이터 폴더 | Settings, Compose 환경변수·mount, `.gitignore`, `.dockerignore`, `activate-release.sh`, 경로·Git 제외 계약 테스트, README |
| bootstrap 데이터·taxonomy | 입력 inventory/hash/count, manifest, component/migration ID, 원본 보존, 초기화·매핑 테스트 |
| normalization 정책 | 설정 fingerprint, mapper와 전체 reclustering의 제약, candidate 진단, 보고서 비교 근거 |
| API 요청·응답·상태 | Pydantic schema, route, Airflow conf, DB 상태, `frontend/src/lib/api.ts`, 화면 polling·오류 처리 |
| DB·발행 | PostgreSQL 제약, DuckDB schema/SQL, transaction·rename·재시도, 이전 snapshot 불변성 |
| 사용자 콘텐츠 | 패키지 resource 위치, wheel 포함 여부, 기본 경로·override, API 테스트, frontend 그림 URL |
| 모델·추출 provider | 프롬프트/strict schema, 인증, model/prompt version, timeout·병렬성, 모델 자산과 image 의존성 |
| 배포·버전 | backend `__version__`/pyproject, frontend package/lock, API version, Compose build args, CI/CD·hook |

## 검증

변경한 동작을 검증하는 가장 작은 범위부터 확인한다. 경로·패키징·pipeline 변경은 실제 bootstrap 입력을 사용하는 회귀 테스트를 포함한다. 전체 파일 포맷 변경이나 무관한 dependency upgrade를 섞지 않는다.

Backend의 CI와 같은 기본 검증:

```bash
cd backend
uv sync --frozen --extra reclustering --dev
uv run ruff check src tests
uv run pytest -q
```

실제 SBERT 추론 검증이 필요하면 `embedding` extra와 로컬 snapshot을 별도로 준비한다. 테스트의 fake extractor/embedder 통과를 실제 LLM·SBERT 호출 성공으로 보고하지 않는다. production provider에서 인증 실패를 가짜 추출로 우회하지 않는다.

Frontend를 변경한 경우:

```bash
cd frontend
npm ci
npm run lint
npm run build
```

배포 설정을 변경한 경우 저장소 루트에서:

```bash
docker compose config --quiet
bash -n deploy/aws/activate-release.sh deploy/aws/user-data.sh scripts/codedeploy/*.sh
git diff --check
```

- backend package resource를 옮겼다면 임시 디렉터리에 wheel을 빌드하고 포함 여부와 설치 후 읽기를 확인한다. 별도 root 파일 COPY에 우연히 의존하지 않게 한다.
- 통합 테스트는 임시 metadata DB·runtime 디렉터리를 사용한다. SQLite 테스트 저장소는 PostgreSQL의 partial unique index 의미를 맞춰야 한다.
- 작업 완료 보고에는 변경 이유, 실행한 검증, 실제로 확인하지 않은 범위를 구분한다. 로컬 테스트 통과를 Docker image build·GUI·원격 배포 성공으로 확대하지 않는다.

## 운영 명령과 장애 대응

실행은 README와 `deploy/aws/README.md`, `deploy/ec2/README.md`를 함께 확인한다. CI는 push·pull request·수동 workflow 실행으로 검증한다. AWS CD는 기본 비활성이며 수동 입력 `deploy_aws=true`, 저장소 변수 `AWS_DEPLOY_ENABLED=true`, `main` 조건을 모두 만족할 때만 실행한다. 새 조직에는 AWS 자격 증명과 배포 변수를 연결하지 않는다.

추출 기본 provider는 `codex_cli`다. 최초 인증:

```bash
docker compose exec airflow-scheduler codex login --device-auth
docker compose exec airflow-scheduler codex login status
```

`CODEX_HOME=/home/airflow/.codex`는 `codex_auth` named volume이다. 일반적인 container/image 재생성에는 유지되지만 `docker compose down -v`는 인증과 운영 volume을 삭제하므로 단순 재배치·재시작에 사용하지 않는다. `CODEX_CLI_VERSION`을 바꿨다면 Airflow image도 재빌드한다. 대안인 `openai` provider는 해당 secret 설정이 필요하다. credential을 Git·로그·보고서에 넣지 않는다.

릴리스가 갱신되지 않으면 다음 순서로 확인한다.

1. `GET /api/pipeline-runs/{id}`의 `state`, `current_task`, `error_message`를 확인한다.
2. `failed` 상태면 해당 Airflow task log를 확인한다. `dispatch_failed`면 API에서 Airflow 실행 요청이 실패했는지 확인한다.
3. `pipeline_succeeded`가 지속되면 FastAPI release finalizer log를 확인한다.
4. `release_failed`여도 기존 current release는 유지된다. 원인을 해결한 뒤 API container에서 `review-catalog-finalize <run_id>`로 재시도한다.
5. DuckDB write 충돌이면 pool·lock과 승인된 두 commit 경로 외의 writer를 조사한다. 잠금을 제거해 문제를 우회하지 않는다.

## 백업과 복구

- PostgreSQL 운영 metadata와 발행 완료 releases를 함께 백업한다. 로컬은 `data/runtime/releases`, Docker는 `catalog_data` volume의 `/data/catalog/releases`가 대상이다.
- 초기화 입력은 활성 manifest의 7개 파일 해시를 보존한다. 진행 중인 work/staging은 retry·finalizer 참조를 확인한 뒤 정리한다. 사용 중인 lock 파일은 삭제하지 않는다.
- 손상된 current release를 복구할 때 `previous_release_id`와 이전 manifest·개별 artifact hash를 검증하고 current pointer를 전환한다. 발행 디렉터리 자체를 수정하지 않는다.
- 백업·복구 절차가 적혀 있다는 이유로 자동화가 구현됐다고 판단하지 않는다. 실제 수행 전 관련 코드와 현재 volume·metadata 상태를 확인한다.
