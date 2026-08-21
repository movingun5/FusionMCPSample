# Fusion 360 사용자 파라미터 MCP 도구 설계

- 상태: 사용자 접근법 승인, 구현 전 검토
- 작성일: 2026-08-21
- 대상 저장소: `movingun5/FusionMCPSample`
- 대상 기능: `upsert_user_parameter`

## 1. 목적과 범위

Codex가 임의 Python을 생성하지 않고도 Fusion 360 사용자 파라미터를 안전하고 반복 가능하게 생성하거나 수정할 수 있도록 명시적 MCP 도구를 추가한다. 첫 번째 파라메트릭 도구이며, 이후 스케치·돌출·구멍 도구가 동일한 파라미터 이름과 표현식을 재사용할 수 있는 기반이 된다.

이번 기능은 다음만 포함한다.

- 사용자 파라미터 생성
- 기존 사용자 파라미터의 표현식과 설명 수정
- 동시 변경 충돌 방지를 위한 선택적 이전 표현식 검사
- 재계산, 실패 복구, 구조화된 결과와 오류
- `$fusion` 스킬과 문서에서 명시적 도구 우선 사용

파라미터 삭제, 모델 파라미터 수정, 여러 파라미터의 일괄 변경, 단위 차원의 강제 변환은 이번 범위에 포함하지 않는다.

## 2. 채택 접근법

하나의 멱등적 MCP 도구를 제공한다.

```text
upsert_user_parameter(
  name,
  expression,
  unit?,
  comment?,
  expected_old_expression?
)
```

생성·수정 도구를 분리하거나 범용 배치 스키마를 도입하지 않는다. 단일 도구는 Codex가 존재 여부를 별도로 분기하지 않아도 되고, 같은 요청을 반복했을 때 중복 파라미터가 생기지 않는다.

## 3. 입력 계약

| 필드 | 필수 | 의미 |
| --- | --- | --- |
| `name` | 예 | Fusion 사용자 파라미터 이름. 1단계에서는 ASCII 식별자 `[A-Za-z_][A-Za-z0-9_]*`만 허용한다. |
| `expression` | 예 | `50 mm`, `plate_width * 2`처럼 Fusion이 평가할 표현식. |
| `unit` | 아니요 | 새 파라미터의 단위. 생략하면 활성 디자인의 기본 길이 단위를 사용한다. 기존 파라미터에서는 호환성 확인용이며 저장된 단위 차원을 임의로 변경하지 않는다. |
| `comment` | 아니요 | 새 파라미터의 설명. 수정 시 생략하면 기존 설명을 유지하고, 빈 문자열이면 설명을 지운다. |
| `expected_old_expression` | 아니요 | 기존 표현식과 정확히 일치할 때만 수정한다. 불일치하면 변경하지 않고 충돌 오류를 반환한다. |

빈 문자열, 알 수 없는 추가 필드, 유효하지 않은 이름은 Fusion API 호출 전에 거부한다. 표현식과 단위의 실제 유효성은 Fusion의 `UnitsManager`와 사용자 파라미터 API로 판정한다.

## 4. 동작 규칙

### 4.1 생성

동일 이름의 사용자 파라미터가 없으면 `ValueInput.createByString(expression)`과 `userParameters.add(...)`로 생성한다. 단위를 생략했으면 문서 기본 길이 단위를 사용한다. 생성 직후 Fusion이 반환한 표현식, 단위, 계산값을 다시 읽는다.

### 4.2 수정

동일 이름의 사용자 파라미터가 있으면 새 객체를 만들지 않고 기존 객체의 표현식을 수정한다. `expected_old_expression`이 제공됐고 실제 값과 다르면 `PARAMETER_CONFLICT`를 반환한다. `comment`가 생략됐으면 보존하고, 제공됐으면 입력값으로 교체한다.

입력 결과가 기존 표현식·설명과 동일하면 `unchanged`로 반환하고 새 체크포인트를 기록하지 않는다.

### 4.3 단위

첫 버전은 기존 파라미터의 단위 차원을 바꾸지 않는다. 수정 요청의 `unit`이 기존 단위와 호환되지 않으면 `PARAMETER_UNIT_MISMATCH`로 중단한다. 표시 단위 변경이 필요하면 같은 차원의 명시적 표현식을 사용한다.

## 5. 트랜잭션과 복구

도구는 Fusion UI 주 스레드에서 실행한다.

1. 변경 전 문서 ID, 타임라인 위치, 파라미터 상태를 캡처한다.
2. Fusion 트랜잭션을 시작한다.
3. 파라미터를 생성하거나 수정한다.
4. `design.computeAll()`을 실행한다.
5. 재계산 실패 또는 예외가 발생하면 트랜잭션을 중단하고 원래 상태를 확인한다.
6. 성공하면 트랜잭션을 커밋하고 최신 MCP 변경 체크포인트를 기록한다.

기존 `undo_last_execution`이 임의 Python뿐 아니라 이 도구의 최신 성공 변경도 되돌릴 수 있도록 체크포인트 저장소를 공통 모듈로 분리한다. 기존 `execute_fusion_python`의 동작과 도구 계약은 유지한다.

파라미터 생성·수정은 사용자가 명시적으로 요청한 일반 모델링 변경으로 처리하며 별도 확인창을 띄우지 않는다. 승인 거부를 우회하거나 삭제 기능을 암묵적으로 추가하지 않는다.

## 6. 결과 계약

성공 결과는 MCP `content`와 `structuredContent`를 모두 제공한다.

```json
{
  "action": "created | updated | unchanged",
  "parameter": {
    "name": "plate_width",
    "expression": "50 mm",
    "unit": "mm",
    "value": 5.0,
    "comment": "Main plate width"
  },
  "previous": null,
  "recomputed": true,
  "checkpoint_recorded": true
}
```

`value`는 Fusion 내부 단위로 반환될 수 있으므로 `expression`과 `unit`을 함께 제공한다. 수정 결과의 `previous`에는 변경 전 표현식·단위·값·설명을 포함한다. `unchanged`에서는 `checkpoint_recorded`가 `false`다.

## 7. 오류 모델

| 코드 | 조건 |
| --- | --- |
| `INVALID_REQUEST` | 이름·표현식·입력 형식이 유효하지 않음 |
| `NO_ACTIVE_DESIGN` | 활성 Fusion 디자인이 없음 |
| `PARAMETER_CONFLICT` | `expected_old_expression` 불일치 |
| `PARAMETER_UNIT_MISMATCH` | 수정 요청 단위가 기존 단위 차원과 호환되지 않음 |
| `PARAMETER_EVALUATION_FAILED` | Fusion이 표현식 또는 단위를 평가하지 못함 |
| `PARAMETER_WRITE_FAILED` | 생성·수정 API가 실패함 |
| `RECOMPUTE_FAILED` | 변경 후 전체 재계산 실패 |

모든 오류는 `isError: true`, 텍스트 `content`, 기계 판독 가능한 오류 세부 정보를 반환하고 토큰이나 전체 traceback을 노출하지 않는다. 상세 traceback은 기존 로컬 감사 로그 정책을 따른다.

## 8. 코드 경계

- `Fusion MCP Addin/fusion/parameters.py`: 입력 검증, 조회, 생성·수정, 결과 직렬화
- `Fusion MCP Addin/fusion/checkpoints.py`: 최신 MCP 변경 체크포인트 저장과 조회
- `Fusion MCP Addin/tools/upsert_user_parameter.py`: MCP 스키마와 주 스레드 핸들러
- `Fusion MCP Addin/tools/__init__.py`: 도구 등록
- `Fusion MCP Addin/fusion/executor.py`: 공통 체크포인트 저장소 사용으로 최소 변경
- `Fusion MCP Addin/tools/undo_last_execution.py`: 공통 체크포인트 조회
- `tests/test_parameters.py`: 파라미터 동작 단위 테스트
- `tests/test_undo.py`, `tests/test_executor.py`: 체크포인트 회귀 테스트
- `README.md`, `skills/fusion/SKILL.md`: 새 명시적 도구와 우선 사용 규칙

Fusion 객체 접근은 `fusion/parameters.py` 안으로 제한하고, 도구 모듈은 등록과 MCP 결과 변환만 담당한다.

## 9. 테스트와 완료 조건

자동화 테스트는 다음을 검증한다.

- 없는 파라미터 생성
- 기존 파라미터 제자리 수정과 중복 방지
- 동일 입력의 `unchanged` 결과
- 설명 생략 시 보존, 빈 문자열 시 삭제
- 이전 표현식 충돌 시 무변경
- 유효하지 않은 이름·표현식·단위 거부
- 재계산 실패 시 트랜잭션 중단과 상태 복구
- 성공 시 공통 체크포인트 기록
- 기존 Python 실행의 undo 동작 회귀 없음
- MCP 성공·오류 응답 형식

실제 Fusion 검증은 빈 임시 문서에서 다음 순서로 수행한다.

1. `codex_test_width = 50 mm` 생성
2. `get_design_context(scope="parameters")`로 확인
3. `expected_old_expression="50 mm"` 조건으로 `60 mm` 수정
4. 컨텍스트에서 새 표현식 확인
5. `undo_last_execution` 후 `50 mm` 복구 확인

실제 문서가 비어 있거나 테스트용이라는 확인 없이 라이브 변경을 실행하지 않는다. 완료 후 서버 버전을 `1.2.0`으로 올리고 전체 테스트를 통과시킨 뒤 `사용자 파라미터 업데이트`가 드러나는 커밋을 GitHub 기능 브랜치에 푸시한다.
