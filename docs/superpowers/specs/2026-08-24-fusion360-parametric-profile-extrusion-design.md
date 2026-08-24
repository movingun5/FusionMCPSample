# Fusion 360 파라메트릭 프로파일 돌출 설계

## 1. 목적

이미지·치수 도면에서 읽은 직선 외곽선을 Fusion의 편집 가능한 파라메트릭 솔리드로 만드는 명시적 MCP 도구 `create_parametric_profile_extrusion`을 추가한다. Codex가 이미지에서 외곽선 꼭짓점과 깊이를 해석하고, Fusion 서버는 구조화된 치수를 검증한 뒤 사용자 파라미터, 폐쇄 스케치, New Body 돌출을 하나의 원자적 작업으로 생성한다.

이 업데이트는 직사각형 전용 `create_parametric_plate`와 임의 Python 사이의 공백을 채운다. L자형, U자형, 계단형처럼 한 개의 직선 폐쇄 외곽선으로 표현되는 프리즘 부품을 안전하게 모델링하는 것이 첫 범위다.

## 2. 범위

포함:

- XY 평면의 3~32개 직선 꼭짓점으로 구성된 단순 폐쇄 다각형
- 꼭짓점별 안전한 키와 X/Y Fusion 길이 expression
- 양수 깊이 expression에 의한 +Z New Body 돌출
- 모든 좌표와 깊이를 이름 있는 `mm` 사용자 파라미터로 생성
- Part Design의 root component와 Hybrid Design의 child component 지원
- 입력 전체 사전 검증, 단일 Fusion transaction, 실패 롤백, 정확한 전체 부품 Undo
- 치수 도면 2뷰 캔버스와 연계한 라이브 검증

제외:

- 원호, 스플라인, 슬롯, 내부 루프, 포켓, 섬, 다중 프로파일
- 음수·대칭·양방향 돌출, Join/Cut/Intersect, 임의 배치·회전
- XZ/YZ 프로파일 생성
- OCR, OpenCV, 자동 윤곽 추적, 원근 보정, 이미지 바이트 처리
- 새 런타임 의존성

후속 업데이트는 호 세그먼트, 내부 루프/포켓, 다른 주 평면, 회전 형상을 각각 독립 기능으로 추가한다.

## 3. MCP 계약

도구 이름은 `create_parametric_profile_extrusion`이다.

```json
{
  "name": "LProfile",
  "parameter_prefix": "l_profile",
  "vertices": [
    {"key": "p1", "x_expression": "-50 mm", "y_expression": "-30 mm"},
    {"key": "p2", "x_expression": "50 mm", "y_expression": "-30 mm"},
    {"key": "p3", "x_expression": "50 mm", "y_expression": "30 mm"},
    {"key": "p4", "x_expression": "10 mm", "y_expression": "30 mm"},
    {"key": "p5", "x_expression": "10 mm", "y_expression": "0 mm"},
    {"key": "p6", "x_expression": "-50 mm", "y_expression": "0 mm"}
  ],
  "depth_expression": "8 mm"
}
```

`name`, `parameter_prefix`, `vertices`, `depth_expression`은 필수다. `vertices` 항목은 `key`, `x_expression`, `y_expression`만 허용하고 추가 필드를 거부한다. 꼭짓점 순서는 외곽선을 도는 순서이며 시계·반시계 방향을 모두 허용한다. 마지막 꼭짓점을 다시 전달하지 않으며 서버가 마지막 점과 첫 점을 연결한다.

생성 파라미터:

- `<prefix>_depth`
- `<prefix>_<vertex-key>_x`
- `<prefix>_<vertex-key>_y`

결과에는 `container_mode`, component/body 이름과 entity token, body summary, 평가된 `depth_mm`, 순서가 보존된 `vertices_mm`, 생성된 파라미터 이름, 재계산·checkpoint 상태를 반환한다. 전체 로컬 이미지 경로나 이미지 바이트는 입력과 결과에 존재하지 않는다.

## 4. 순수 검증과 기하 계산

`fusion/profile_geometry.py`가 Fusion entity를 만들기 전에 요청을 정규화하고 검증한다.

문자열 검증:

- 표시 이름은 비어 있거나 제어 문자를 포함할 수 없다.
- prefix와 vertex key는 `[A-Za-z_][A-Za-z0-9_]*`와 일치해야 한다.
- vertex key는 중복될 수 없다.
- 모든 expression은 비어 있지 않은 문자열이어야 한다.

평가 후 기하 검증:

- 꼭짓점 수는 3~32개다.
- `depth > 0`이어야 한다.
- 인접 꼭짓점과 마지막/첫 꼭짓점은 같은 좌표일 수 없다.
- 서로 인접하지 않은 선분은 교차하거나 접촉할 수 없다.
- 신발끈 공식의 절대 면적이 `1e-9 cm²`보다 커야 한다.
- 좌표와 깊이는 Fusion units manager로 길이 expression으로 평가한다.

기하 오류는 Fusion transaction 전에 반환한다. 안정된 오류 코드는 `PROFILE_EXPRESSION_INVALID`, `PROFILE_DEPTH_INVALID`, `PROFILE_VERTEX_DUPLICATE`, `PROFILE_SELF_INTERSECTION`, `PROFILE_AREA_INVALID`이다. JSON 구조와 식별자 오류는 `INVALID_REQUEST`다.

## 5. Fusion 생성 구조

`fusion/profile_builder.py`는 transaction·감사 로그·checkpoint를 소유하지 않고 entity 생성만 담당한다.

1. Part Design이면 root component를 사용하고 `container_mode = root_part`로 기록한다.
2. Hybrid Design이면 identity transform의 child component 하나를 만든다.
3. depth 및 모든 vertex X/Y 사용자 파라미터를 생성한다.
4. XY construction plane에 `<name>_Profile` 스케치를 만든다.
5. 평가된 좌표에 SketchPoint를 만들고 순서대로 `addByTwoPoints`로 연결해 마지막 점과 첫 점을 닫는다.
6. 각 비영점 좌표는 origin과 해당 SketchPoint 사이의 driving distance dimension으로 생성된 파라미터를 참조한다. 음수 좌표는 기존 hole placement와 같은 양수 거리 expression 변환을 사용한다.
7. 정확히 한 개의 유효 폐쇄 profile이 있는지 확인한다.
8. `<prefix>_depth`를 사용하는 `<name>_Extrusion` New Body를 만들고 body 이름을 `<name>`으로 지정한다.

실패 단계는 `component`, `parameters`, `sketch`, `extrusion`, `verification`으로 구분한다.

## 6. 원자성, 롤백, Undo

`fusion/parametric_profiles.py`가 다음 순서를 소유한다.

1. active design, user parameters, units manager 확인
2. 순수 요청 정규화·평가
3. 생성될 모든 파라미터 이름 충돌 검사
4. 시작 snapshot/count 저장
5. `PTransaction.Start "Create Parametric Profile Extrusion"`
6. builder 실행 및 `design.computeAll()`
7. body +1, Part component +0 또는 Hybrid component +1 검증
8. transaction commit, 감사 로그, checkpoint 기록

실패 시 transaction abort 후 시작 count와 같으면 Fusion 복원을 authoritative result로 사용한다. 그렇지 않으면 builder가 생성 occurrence 또는 root-part의 정확한 feature/sketch와 파라미터를 역순으로 제거한다. 실패 후 count가 복원되지 않으면 `ROLLBACK_FAILED`를 반환한다.

checkpoint mutation은 `create_parametric_profile_extrusion`이다. occurrence/component/body token, extrusion token, profile sketch token, parameter names, starting/created counts를 기록한다. `undo_last_execution`은 모든 대상을 먼저 확인한 뒤 한 transaction에서 정확한 profile extrusion entity만 제거한다. 다른 body나 파라미터는 건드리지 않는다.

## 7. 이미지·도면 워크플로

이미지 해석은 Codex가 담당한다.

1. top/plan 도면을 XY 캔버스로, front 도면을 XZ 캔버스로 분류한다.
2. `create_orthographic_canvas_set`으로 공통 X 치수를 검증하고 두 이미지를 원자 배치한다.
3. 도면에서 읽은 꼭짓점과 깊이를 `create_parametric_profile_extrusion`에 전달한다.
4. `get_design_context`로 body bounds와 파라미터를 확인한다.
5. top/front/isometric screenshot을 캔버스와 비교한다.
6. 불일치하면 추측으로 보정하지 않고 명시적 파라미터 변경 또는 Undo를 사용한다.

라이브 fixture는 서로 다른 PNG 두 장을 사용한다. Top은 `100 × 60 mm` 외곽에서 좌상단 `60 × 30 mm` 영역이 제거된 L 프로파일을 표시하고, Front는 공통 폭 `100 mm`와 깊이 `8 mm`를 표시한다. 이미지는 Windows 기본 `System.Drawing`으로 결정론적으로 생성하며 제품 runtime에는 의존성을 추가하지 않는다.

## 8. 도구 등록, 버전, 문서

- 서버 버전: `2.3.0`
- 등록 도구 수: 22개
- 새 파일: `profile_geometry.py`, `profile_builder.py`, `parametric_profiles.py`, `tools/create_parametric_profile_extrusion.py`
- 수정: tool registry, status version, Undo, fakes, README 두 곳, Fusion image-modeling reference, live validation 문서
- 기본 `fusion/SKILL.md`에는 한 줄 라우팅만 추가하고 상세 도면 절차는 `references/image-modeling.md`에 둔다.

## 9. 테스트와 완료 기준

자동 테스트는 다음을 포함한다.

- strict normalization, fresh copies, safe identifiers, 3/32 경계
- Fusion expression 평가와 parameter naming/order
- 중복 인접점, self-intersection/touch, 면적 0, 비양수 depth 거부
- L/U/계단형 단순 다각형 허용과 시계/반시계 허용
- Part root와 Hybrid child component 생성
- 좌표 dimension, 폐쇄 line count, 단일 profile, New Body depth parameter
- 단계별 실패 롤백과 transaction-restored handle 처리
- exact-target whole-part Undo와 다른 entity 보존
- strict MCP schema, 22개 고유 도구, 서버 2.3.0
- fixture 생성과 live harness의 base64/path redaction

라이브 완료 기준:

- Fusion 2704.1.53에서 서버 2.3.0과 22개 도구 확인
- 두 distinct drawing canvas가 XY/XZ에 배치되고 공통 X 차이 0 mm
- L profile body bounds `100 × 60 × 8 mm` 이내 오차 0.01 mm
- top/front/isometric 화면이 도면과 일치
- invalid bow-tie profile이 `PROFILE_SELF_INTERSECTION`으로 geometry delta 없이 거부
- 전체 profile Undo가 캔버스를 제외한 profile body/sketch/feature/parameters만 제거
- STEP/STL export 성공
- 전체 자동 테스트, compileall, `git diff --check` 통과

## 10. 안전과 개인정보 경계

- Fusion API 호출은 기존 CustomEvent/task queue를 통해 UI thread에서 실행한다.
- arbitrary Python을 사용하지 않는다.
- URL, 상대 경로, 이미지 바이트를 새 도구에 전달하지 않는다.
- 캔버스 결과와 감사 로그는 기존처럼 image basename만 노출한다.
- 기존 사용자 설계에서 이름·파라미터 충돌이 있으면 생성 전에 중단한다.
- Assembly Design external part 생성은 지원하지 않으며 구조화 오류로 반환한다.
