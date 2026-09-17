"""평가 하네스 — 골든셋으로 사전 점검의 정확도를 잰다.

    python -m adpolicy.evalkit                 # 터미널 요약
    python -m adpolicy.evalkit --md report.md  # 마크다운 리포트
    python -m adpolicy.evalkit --fail-under 0.8  # CI용 (F1 미달 시 종료 코드 1)

왜 필요한가
    v1은 "이 페이지가 정책에 걸릴 것 같다"를 예측하지만, 그 예측이 맞았는지
    확인하는 장치가 없었다. 채점표 없는 예측은 개선할 방향을 알려주지 않는다.
"""

from .loader import GoldenError, build_scope, load_cases
from .models import CaseResult, CodeMetric, EvalReport, GoldenCase
from .report import critical_false_alarms, render_console, render_markdown
from .runner import run_all, run_case

__all__ = [
    "CaseResult", "CodeMetric", "EvalReport", "GoldenCase", "GoldenError",
    "build_scope", "critical_false_alarms", "load_cases", "render_console",
    "render_markdown", "run_all", "run_case",
]
