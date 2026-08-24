# Fusion 360 이미지·도면 기반 모델링 1단계 설계

- 상태: 접근법 승인, 구현 전 사용자 확인
- 작성일: 2026-08-24
- 대상 저장소: `movingun5/FusionMCPSample`
- 대상 버전: `2.0.0`
- 대상 기능: Codex 이미지 분석과 보정된 Fusion 참조 캔버스

## 1. 목적

Codex가 사용자가 첨부한 치수 도면을 해석하고, 동일 이미지를 Fusion 360의 기준 평면에 실제 치수로 배치한 다음 기존 명시적 CAD 도구로 모델을 생성하고 직교 화면으로 비교할 수 있게 한다.

이번 단계는 이미지·도면 기반 모델링 계획의 첫 구현이다. 정확한 치수가 표시된 정면도, 평면도 또는 측면도 한 장을 우선 지원한다. Codex의 이미지 이해 기능이 형상과 치수를 해석하며 Fusion MCP 서버는 이미지 분석 모델을 내장하지 않는다.

## 2. 채택 접근법

다음 역할 분리를 채택한다.

```text
사용자 이미지 첨부
  → Codex가 뷰, 형상, 치수, 단위, 불확실성 추출
  → create_reference_canvas로 Fusion에 실제 크기 배치
  → 기존 명시적 스케치·돌출·구멍·필렛·모따기·패턴 도구 실행
  → 직교 Fusion 스크린샷과 원본 도면 비교
  → 수치와 화면이 모두 일치할 때만 완료
```

서버 내부 OCR 또는 컴퓨터 비전, 외부 AI API, 자동 윤곽 추적은 추가하지 않는다. 이 구조는 모델 해석과 Fusion API 실행을 분리하고 새 런타임 의존성을 만들지 않는다.

## 3. 사용자 워크플로

1. 사용자가 ChatGPT/Codex 대화에 도면 이미지를 첨부한다.
2. Codex는 도면 종류, 표시 뷰, 단위, 외곽 치수, 구멍과 반복 형상, 깊이 정보를 구조화한다.
3. 누락된 깊이처럼 결과 형상을 바꾸는 정보가 없으면 한 가지 질문만 한다. 추측으로 3D 깊이를 만들지 않는다.
4. 이미지의 로컬 절대 경로가 사용 가능한 경우 `create_reference_canvas`로 주 기준 뷰를 배치한다.
5. 기존 명시적 MCP 도구를 우선 사용해 형상을 만든다. 지원되지 않는 한 개의 응집된 피처 그룹에만 제한적 Python 실행을 사용한다.
6. 모델 수치와 원본 치수를 비교하고, 해당 뷰의 직교 스크린샷을 원본과 시각적으로 비교한다.
7. 불일치 시 최신 변경을 Undo하거나 안전한 파라미터 수정 도구로 조정한다.

이미지 첨부가 모델 서비스로 전송될 수 있다는 기존 데이터 경계를 유지한다. Fusion 캔버스 파일은 로컬 경로에서 로컬 Fusion 문서로 가져오며 MCP 결과에 이미지 원본 바이트를 다시 반환하지 않는다.

## 4. 새 MCP 도구

```text
create_reference_canvas(
  name,
  image_path,
  plane,
  width_expression,
  center_x_expression="0 mm",
  center_y_expression="0 mm",
  opacity=50,
  flip_horizontal=false,
  flip_vertical=false
)
```

### 4.1 입력 계약

| 필드 | 필수 | 의미 |
| --- | --- | --- |
| `name` | 예 | 활성 컴포넌트에서 유일한 캔버스 이름. 공백만 있는 이름은 거부한다. |
| `image_path` | 예 | 존재하는 로컬 이미지의 절대 경로. URL과 상대 경로는 거부한다. |
| `plane` | 예 | `xy`, `xz`, `yz` 중 하나인 기본 구성 평면. |
| `width_expression` | 예 | 캔버스의 실제 전체 가로 길이를 정의하는 양수 Fusion 길이 표현식. |
| `center_x_expression` | 아니요 | 선택한 평면의 로컬 X 방향 캔버스 중심. 기본값 `0 mm`. |
| `center_y_expression` | 아니요 | 선택한 평면의 로컬 Y 방향 캔버스 중심. 기본값 `0 mm`. |
| `opacity` | 아니요 | 0부터 100까지의 정수. 기본값 50. |
| `flip_horizontal` | 아니요 | 이미지의 수평 방향 반전. 기본값 false. |
| `flip_vertical` | 아니요 | 이미지의 수직 방향 반전. 기본값 false. |

허용 확장자는 대소문자를 구분하지 않는 `.png`, `.jpg`, `.jpeg`, `.tif`, `.tiff`다. 일반 파일만 허용하고 최대 크기는 25 MiB로 제한한다. 심볼릭 링크 또는 재분석 지점은 최종 해석 경로가 실제 파일일 때만 허용한다. 정규화 후에도 절대 경로가 아니거나 파일이 사라졌으면 변경 전에 실패한다.

## 5. 캔버스 크기와 위치

Fusion의 `Canvases.createInput(imageFilename, planarEntity)`로 기본 `CanvasInput`을 만든다. 기본 변환 행렬의 X·Y 벡터 길이에서 원본 이미지 종횡비를 얻는다. 별도의 Pillow 의존성은 사용하지 않는다.

1. `width_expression`을 활성 문서 기본 길이 단위로 평가한다.
2. 평가 결과를 Fusion 내부 길이 단위인 cm로 유지한다.
3. 기본 행렬에서 `aspect_ratio = x_length / y_length`를 계산한다.
4. X 벡터 길이를 요청한 가로 길이로 설정한다.
5. Y 벡터 길이를 `width / aspect_ratio`로 설정한다.
6. 중심 표현식을 평가해 행렬 원점을 배치한다.
7. 수평·수직 반전이 요청되면 해당 축 벡터의 방향만 반전한다.

종횡비가 0이거나 유한하지 않으면 변경하지 않고 오류를 반환한다. 첫 버전은 회전 각도, 임의 면, 비균일 스케일, 원근 보정을 지원하지 않는다.

## 6. Fusion 실행과 복구

도구는 기존 작업 큐를 통해 Fusion UI 주 스레드에서 실행한다.

1. 활성 디자인, 활성 컴포넌트, 캔버스 컬렉션, 구성 평면을 다시 얻는다.
2. 모든 문자열, 파일, 표현식, 투명도, 이름 충돌을 변경 전에 검증한다.
3. 문서 ID와 타임라인 위치를 캡처하고 Fusion 트랜잭션을 시작한다.
4. `CanvasInput`을 만들고 변환, 투명도, 렌더링·표시 옵션을 설정한다.
5. 캔버스를 추가하고 고유 이름을 지정한다.
6. 디자인을 재계산하고 생성된 캔버스의 이름, 토큰, 변환을 다시 읽는다.
7. 성공 시 커밋하고 공통 Undo 체크포인트를 기록한다.
8. 실패 시 트랜잭션을 중단한다. 트랜잭션이 없었던 경우 부분 생성된 캔버스를 삭제한다.

캔버스는 기본적으로 선택 가능, 모델을 통해 표시, 렌더 워크스페이스에서는 비렌더링 상태로 만든다. 모델링 기준으로만 사용하며 최종 렌더 자산으로 취급하지 않는다.

## 7. 결과와 개인정보 경계

성공 결과 예시는 다음과 같다.

```json
{
  "action": "created",
  "canvas": {
    "name": "front_reference",
    "entity_token": "...",
    "image_name": "front.png",
    "plane": "xy",
    "width_mm": 100.0,
    "height_mm": 60.0,
    "center_mm": [0.0, 0.0],
    "opacity": 50,
    "flip_horizontal": false,
    "flip_vertical": false
  },
  "recomputed": true,
  "checkpoint_recorded": true
}
```

구조화된 결과, 오류, 감사 로그에는 전체 `image_path`를 넣지 않는다. 기본 파일명, 확장자, 파일 크기와 성공 여부만 기록할 수 있다. 이미지 바이트, 사용자 폴더 경로, 인증 토큰, 전체 traceback은 원격 응답에 포함하지 않는다.

## 8. 디자인 컨텍스트 확장

`get_design_context`의 각 컴포넌트 요약에 다음을 추가한다.

- `canvas_count`
- 제한 범위 안의 `canvases` 배열
- 캔버스 이름과 엔티티 토큰
- 기준 평면 종류를 확인할 수 있는 정보
- 가로·세로 크기, 중심, 투명도
- 이미지 기본 파일명만 포함한 `image_name`

`scope="components"`와 `scope="all"`에서 캔버스를 노출한다. 기존 전체 `limit`을 공유해 큰 문서에서 응답 크기를 제한한다. 기존 필드는 변경하거나 제거하지 않는다.

## 9. 오류 모델

| 코드 | 조건 |
| --- | --- |
| `INVALID_REQUEST` | 이름, 평면, 불리언, 투명도 또는 문자열 형식이 잘못됨 |
| `NO_ACTIVE_DESIGN` | 활성 Fusion 디자인이 없음 |
| `REFERENCE_IMAGE_PATH_INVALID` | 상대 경로, URL, 지원하지 않는 확장자 또는 일반 파일이 아님 |
| `REFERENCE_IMAGE_NOT_FOUND` | 정규화한 파일이 존재하지 않음 |
| `REFERENCE_IMAGE_TOO_LARGE` | 파일이 25 MiB를 초과함 |
| `CANVAS_NAME_CONFLICT` | 활성 컴포넌트에 같은 이름의 캔버스가 있음 |
| `CANVAS_EXPRESSION_INVALID` | 크기 또는 중심 표현식을 평가할 수 없음 |
| `CANVAS_SIZE_INVALID` | 가로 길이가 0 이하이거나 종횡비가 유효하지 않음 |
| `CANVAS_WRITE_FAILED` | Fusion이 입력 또는 캔버스를 생성하지 못함 |
| `RECOMPUTE_FAILED` | 생성 후 디자인 재계산 실패 |

모든 오류는 기존 MCP 오류 구조를 사용하며 변경 전 검증 오류는 트랜잭션과 체크포인트를 만들지 않는다.

## 10. Fusion 스킬의 점진적 공개

기본 `skills/fusion/SKILL.md`에는 이미지·도면 요청을 식별하고 세부 참조 문서를 읽으라는 짧은 라우팅 규칙만 추가한다. 상세 절차는 `skills/fusion/references/image-modeling.md`에 둔다.

참조 문서는 다음을 규정한다.

- 치수 도면과 사진을 먼저 구분
- 도면의 단위, 뷰, 외곽 치수, 반복 형상, 깊이를 추출
- 명시된 치수와 추정치를 분리
- 필수 치수가 없으면 한 질문만 하고 중단
- 주 기준 뷰 하나만 캔버스로 배치
- 기존 명시적 CAD 도구를 우선 사용
- 해당 도면 뷰와 같은 직교 Fusion 스크린샷으로 비교
- 가려짐, 원근, 왜곡 때문에 확인할 수 없는 항목을 성공으로 간주하지 않음

이 구조는 일반 Fusion 작업이 이미지 모델링 세부 지침을 매번 읽지 않도록 한다. 별도 `fusion-image-modeling` 스킬로 분리하는 결정은 실제 사용 사례가 쌓인 뒤 다시 평가한다.

## 11. 코드 경계

- `Fusion MCP Addin/fusion/canvases.py`: 파일·입력 검증, 변환 계산, 캔버스 생성, 결과 직렬화
- `Fusion MCP Addin/tools/create_reference_canvas.py`: 엄격한 MCP 입력 스키마와 핸들러
- `Fusion MCP Addin/tools/__init__.py`: 도구 등록
- `Fusion MCP Addin/fusion/context.py`: 제한된 캔버스 컨텍스트
- `tests/test_canvases.py`: 캔버스 동작과 오류 단위 테스트
- `tests/test_reference_canvas_tool.py`: MCP 스키마 테스트
- `tests/test_context.py`: 캔버스 컨텍스트 회귀 테스트
- `skills/fusion/SKILL.md`: 이미지·도면 라우팅 한 줄
- `skills/fusion/references/image-modeling.md`: 필요할 때만 읽는 상세 워크플로
- `README.md`, `Fusion MCP Addin/README.md`, `docs/live-validation.md`: 사용자 문서와 검증 상태

기존 스케치·피처 모듈은 수정하지 않는다. 파일 검사와 경로 비공개 처리는 `fusion/canvases.py` 안에서 끝내며 일반 임의 Python 정책을 약화하지 않는다.

## 12. 테스트와 완료 조건

자동화 테스트는 다음을 검증한다.

- PNG, JPEG, TIFF 절대 경로 허용
- 상대 경로, URL, 누락 파일, 지원하지 않는 확장자, 25 MiB 초과 파일 거부
- 잘못된 평면, 투명도, 불리언, 빈 이름 거부
- 가로 표현식과 중심 표현식 평가
- 원본 종횡비 유지와 mm 결과 변환
- 수평·수직 반전 벡터 방향
- 같은 이름의 캔버스 중복 거부
- Fusion 입력·추가 실패의 구조화된 오류
- 재계산 실패 시 트랜잭션 중단과 부분 생성 제거
- 성공 시 공통 체크포인트 기록과 Undo 호환
- 전체 경로가 MCP 결과와 감사 로그에 없는지 확인
- 디자인 컨텍스트의 제한·캔버스 요약
- 엄격한 MCP 스키마와 기존 테스트 회귀 없음

라이브 검증은 빈 미저장 디자인과 저장소 안의 비민감 테스트 이미지에서 수행한다.

1. 서버 `2.0.0`과 새 도구 검색 확인
2. XY 평면에 테스트 이미지를 가로 `100 mm`, 중심 `(0, 0)`, 투명도 50으로 배치
3. 컨텍스트에서 이름, 캔버스 수, 가로·세로 크기, 중심, 투명도 확인
4. 상단 스크린샷에서 이미지 비율과 중심 배치 확인
5. `undo_last_execution` 후 캔버스 수가 원래 값으로 복구되는지 확인

완료 시 전체 자동 테스트, `compileall`, `git diff --check`, 설치 진단을 실행한다. 설치된 Fusion 애드인과 Fusion 스킬을 갱신하고, 구현과 라이브 검증을 각각 한국어 업데이트 커밋으로 GitHub 기능 브랜치에 푸시한다.

## 13. 후속 범위

다음 기능은 이번 구현에 포함하지 않고 이미지·도면 기반 모델링의 후속 업데이트로 둔다.

- 사진과 자유형 실루엣의 자동 윤곽 추출
- 여러 직교 뷰의 동시 정렬과 상호 치수 검증
- 회전, 임의 면, 비균일 스케일, 원근 왜곡 보정
- SVG 자동 생성·스케치 가져오기
- OCR 엔진 또는 외부 비전 API
- 도면 공차, GD&T, 표면 거칠기와 재료 해석
- 이미지 유사도 점수의 자동 계산
