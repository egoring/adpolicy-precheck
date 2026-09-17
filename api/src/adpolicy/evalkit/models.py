"""평가 하네스의 자료형.

설계 판단 — 왜 `expect`와 `forbid`를 나누는가
    골든 케이스에 "이 코드가 나와야 한다"만 적으면, 정상 페이지에서 엉뚱한
    코드가 뜨는 오탐을 잡을 수 없다. v1에서 실제로 겪은 사고가 그것이었다
    (정상 쇼핑몰이 계정 정지급 ABUSE-CLOAKING으로 보고됨). 그래서 두 축을 둔다.

        expect  이 케이스에서 반드시 나와야 하는 코드
        forbid  이 케이스에서 나오면 오탐인 코드

설계 판단 — 왜 `scope`가 필요한가
    골든셋에 적지 않은 코드가 결과에 섞여 나왔을 때 전부 오탐으로 치면
    라벨링 부담이 폭발한다(56개 코드를 케이스마다 전부 판정해야 한다).
    그래서 **채점 범위(scope)** 를 둔다. scope 안의 코드만 채점하고,
    밖의 코드는 `unscored`로 따로 세어서 리포트에 드러낸다.
    숨기지 않되, 라벨이 없는 것을 틀렸다고 말하지도 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GoldenCase:
    """라벨링된 평가 케이스 하나."""

    id: str
    html: str                       # 페이지 원문 (loader가 파일에서 읽어 채운다)
    url: str = "https://example.com/lp"
    final_url: str = ""             # 비우면 url과 같다고 본다
    status_code: int = 200
    ad_copy: str = ""
    headlines: tuple[str, ...] = ()
    descriptions: tuple[str, ...] = ()
    platform: str = "google_ads"

    expect: tuple[str, ...] = ()    # 반드시 나와야 하는 코드
    forbid: tuple[str, ...] = ()    # 나오면 오탐인 코드
    note: str = ""                  # 이 케이스가 무엇을 재는지 (사람용)
    source: str = ""                # 실제 사례에서 왔다면 출처

    @property
    def resolved_final_url(self) -> str:
        return self.final_url or self.url


@dataclass
class CaseResult:
    """케이스 하나를 돌린 결과."""

    case_id: str
    produced: set[str] = field(default_factory=set)   # 실제로 나온 코드 전체
    hit: set[str] = field(default_factory=set)        # expect 중 맞춘 것
    missed: set[str] = field(default_factory=set)     # expect 중 못 잡은 것 (FN)
    false_alarm: set[str] = field(default_factory=set)  # forbid인데 나온 것 (FP)
    unscored: set[str] = field(default_factory=set)   # scope 밖이라 채점 안 한 코드
    error: str = ""                                   # 실행 자체가 실패했을 때

    @property
    def ok(self) -> bool:
        return not self.error and not self.missed and not self.false_alarm


@dataclass
class CodeMetric:
    """코드 하나에 대한 지표. 표본 수를 반드시 같이 들고 다닌다 —
    표본 3건짜리 F1은 숫자일 뿐 의미가 없다."""

    code: str
    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0

    @property
    def support(self) -> int:
        """이 코드가 정답으로 등장한 케이스 수 (= TP + FN)."""
        return self.tp + self.fn

    @property
    def scored(self) -> int:
        """이 코드가 채점된 케이스 수."""
        return self.tp + self.fp + self.fn + self.tn

    @property
    def precision(self) -> float | None:
        d = self.tp + self.fp
        return self.tp / d if d else None

    @property
    def recall(self) -> float | None:
        d = self.tp + self.fn
        return self.tp / d if d else None

    @property
    def f1(self) -> float | None:
        p, r = self.precision, self.recall
        if p is None or r is None or p + r == 0:
            return None
        return 2 * p * r / (p + r)


@dataclass
class EvalReport:
    """전체 결과."""

    results: list[CaseResult] = field(default_factory=list)
    per_code: dict[str, CodeMetric] = field(default_factory=dict)
    scope: set[str] = field(default_factory=set)
    elapsed_sec: float = 0.0

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.ok)

    @property
    def errored(self) -> list[CaseResult]:
        return [r for r in self.results if r.error]

    def totals(self) -> tuple[int, int, int]:
        """(TP, FP, FN) 합계 — micro 평균의 재료."""
        tp = sum(m.tp for m in self.per_code.values())
        fp = sum(m.fp for m in self.per_code.values())
        fn = sum(m.fn for m in self.per_code.values())
        return tp, fp, fn

    def micro(self) -> tuple[float | None, float | None, float | None]:
        tp, fp, fn = self.totals()
        p = tp / (tp + fp) if (tp + fp) else None
        r = tp / (tp + fn) if (tp + fn) else None
        f = (2 * p * r / (p + r)) if (p and r and p + r) else None
        return p, r, f

    def macro(self) -> tuple[float | None, float | None, float | None]:
        """코드별 지표의 단순 평균. 표본이 적은 코드도 같은 무게를 갖는다 —
        micro만 보면 흔한 코드가 전체 숫자를 지배한다."""
        ps = [m.precision for m in self.per_code.values() if m.precision is not None]
        rs = [m.recall for m in self.per_code.values() if m.recall is not None]
        fs = [m.f1 for m in self.per_code.values() if m.f1 is not None]
        avg = lambda xs: (sum(xs) / len(xs)) if xs else None  # noqa: E731
        return avg(ps), avg(rs), avg(fs)
