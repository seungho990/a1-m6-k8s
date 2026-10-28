# A1-M6 — CSV 규칙 판정 + TF-IDF/BM25 근거 검색 통합

**이 프로젝트는 앞선 A1-M2~M5의 최신 CSV 구조만 사용합니다.** YAML, rule_history.csv, knowledge_records.csv를 사용하지 않습니다.

## A1 시나리오
1. `data/rules.csv`는 규칙 원본(8개: `applied` 7, `proposed` 1)
2. `data/rule_tree.csv`는 `node_id/parent_id/file/rule_id`로 규칙 위치를 관리
3. `checker.py`는 M2의 CSV 규칙 검사기. `search_engine.py`는 M3의 TF-IDF·BM25 검색기
4. `metrics.py`는 M4의 성능 평가 함수, `cleaner.py`는 M5의 텍스트 정제 정책
5. `pipeline.py`가 검사→현재 적용 규칙 직접 연결→관련 규칙 후보 검색→판정 결과 생성
6. `db.py`가 검사 실행과 판정 내역 저장. `api.py`, `web/index.html`에서 실제 조회

## 1. 로컬에서 최소 실행
```powershell
python -m pip install -r requirements.txt
$env:APP_ENV = 'development'
$env:DATABASE_URL = 'sqlite:///./inspect_demo.db'
python evaluate_baseline.py
python -m pytest -q
python -m uvicorn api:app --host 127.0.0.1 --port 8000
```

웹에서 `http://127.0.0.1:8000/` 에 접속하여 HTML을 입력하고 `검사 실행` 버튼을 누릅니다. 조회 표의 **직접 규칙**은 rule_id로 정확히 연결한 원본이고 **검색 후보**는 TF-IDF/BM25가 찾아낸 참고 문서입니다. 두 종류 모두 WCAG 인증 결과가 아닙니다.

`GET /health`는 앱 프로세스, `GET /ready`는 CSV 검증+DB 연결을 확인합니다. `GET /api/cache`는 현재 규칙·트리·전처리 버전을 표시합니다. `/docs`는 개발용 OpenAPI 문서입니다.

## 2. 결과 저장
운영환경의 `DATABASE_URL`은 MySQL로 설정합니다. **가비아 Pod에서 VM의 MySQL에 접근 가능한 사설 네트워크/VPN 등을 먼저 구성해야 합니다.** 개발 노트북의 `127.0.0.1:3307` SSH 포워딩 주소는 가비아 Pod에서 유효하지 않습니다. 공인 인터넷에 MySQL의 3306 포트를 개방하지 않습니다.

```powershell
# 로컬 Windows에서 안전한 테스트용 별도 DB 계정 사용 예시
$env:DATABASE_URL = 'mysql+pymysql://inspect_user:ENCODED_PASSWORD@REACHABLE_MYSQL_HOST:3306/inspect_db?charset=utf8mb4'
```

`inspection_runs`, `inspection_findings` 테이블에 검사 ID·입력 해시·버전 해시·판정 결과를 저장합니다. **입력한 HTML 원문은 저장하지 않습니다.** 이력·검색 결과에는 페이지의 HTML에서 유래한 속성 값이나 텍스트가 일부 포함될 수 있으므로 실제 개인 정보는 제출하지 마세요. `create_all()`은 교육용이며 스키마 변경의 정식 배포에는 Alembic 등을 사용하세요.

## 3. 캐시 전략과 데이터 갱신
캐시 키 = `SHA256(HTML) + SHA256(rules.csv) + SHA256(rule_tree.csv) + preprocess_version + method + k`

- 동일 요청은 캐시 계산 결과 재사용, **새 run_id로 다시 저장**
- CSV 변경 시 메모리 캐시 폐기, 규칙·트리 정합성 재검증
- `status=proposed`는 판정 및 현행 검색 대상에서 제외
- Pod 내 메모리 캐시이므로 여러 Pod 간 캐시 공유는 없음. A4에서 다중 Pod 전략 재설계
- 컨테이너 이미지는 불변이므로 **배포 중 CSV를 수정하는 방식이 아니라 Git 변경 → 새 이미지 → Helm 업데이트**로 새 규칙 버전을 반영

## 4. Git CI → GHCR → 가비아 K3s/Helm
Git 기초는 반복하지 않습니다. `main` 푸시 시 `.github/workflows/ci.yml`이 테스트 후 **커밋 SHA 태그**로 GHCR 이미지를 빌드·발행합니다. 이 CI가 Helm까지 자동 변경하는 것은 아닙니다. 배포자는 승인된 SHA로 명시적 갱신합니다.

```bash
helm upgrade --install a1-m6 ./chart/a1-m6 -n a1-m6 --create-namespace \
  --set image.repository=ghcr.io/YOUR-OWNER/YOUR-REPO \
  --set image.tag=ACTUAL_GIT_SHA
kubectl -n a1-m6 rollout status deployment/a1-m6
kubectl -n a1-m6 port-forward svc/a1-m6 8080:80
```

운영 시 Secret `a1-m6-app-secrets`에는 `DATABASE_URL`, `BASIC_USER`, `BASIC_PASSWORD`가 필요합니다. GHCR 패키지가 Private이라면 `imagePullSecrets`도 설정합니다. 기본 Ingress는 **비활성**이며, 도메인·TLS·로그인·인증 방식을 검증한 후 외부에 공개합니다. 이미 설치된 가비아 K3s·Helm을 사용하므로 설치 과정은 없습니다.

`Dockerfile`은 OCI 이미지 **빌드 용도**입니다. 별도의 `docker run` 기반 운영은 하지 않으며 K3s 기본 containerd로 실행합니다.

## 5. M4 평가와 회귀 검증
```bash
python evaluate_baseline.py
python -m pytest -q
```
교육용 Gold 데이터는 단순한 실행 회귀 확인에 사용합니다. 표본 데이터에서 높은 점수는 일반적인 탐지 정확도나 WCAG 준수 보증이 아닙니다.

## 6. 보안·현실적 한계
- 이 버전은 **HTML 문자열**만 받습니다. 외부 URL 자동 수집은 SSRF 위험이 있으므로 넣지 않았습니다.
- 검사는 일부 HTML 정적 구조만 확인하며 완전한 WCAG 접근성 인증이 아닙니다.
- Basic 인증은 교육용 보호 계층입니다. 공개 서비스에서는 TLS·접근 제어·속도 제한·권한 검토 등이 필요합니다.
- `rules.csv` 및 트리를 최신 M2 데이터와 동일하게 유지합니다. **이전 YAML M6 코드를 섞지 않습니다.**
- 실제 가비아 K3s 배포 및 운영 MySQL 연결은 제공 환경에서 직접 검증해야 합니다. 이 자료의 로컬 테스트 통과만으로 외부 배포 완료를 주장하지 않습니다.

© 2026 부성순. All rights reserved. WCAG 등 외부 자료는 각 저작권자의 권리에 따릅니다.
