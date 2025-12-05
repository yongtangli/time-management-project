# core/optimizer.py
# 以 PuLP 建兩種最佳化：
# A) optimize_minutes: 將「今日總分鐘」分配給各科（連續變數）
# B) optimize_blocks:  將「30 分鐘 block」指派給各科（0/1 整數規劃）

from __future__ import annotations
import math
from datetime import datetime, date, timedelta
from typing import Dict, List, Tuple, Optional

import pandas as pd
from dateutil import parser as dateparser
import pulp

# ---- 可調參數 ---------------------------------------------------------------

CATEGORY_COEFS: Dict[str, float] = {
    "必修": 1.30,
    "選修": 1.00,
    "通識": 0.85,
    "實驗": 1.10,
}

BETA_DIFFICULTY = 0.10          # 難度加成(每 1 點 +10%)
GAMMA_NEAR_EXAM = 0.80          # 考前加權影響上限
EXAM_HORIZON_DAYS = 21          # 距考 n 天內開始加權

# ---------------------------------------------------------------------------

def _safe_parse_date(s: str | float | None) -> Optional[date]:
    if s is None:
        return None
    if isinstance(s, float) and math.isnan(s):
        return None
    s = str(s).strip()
    if not s:
        return None
    try:
        return dateparser.parse(s).date()
    except Exception:
        return None

def compute_course_weight(
    row: pd.Series,
    today: Optional[date] = None,
    category_coefs: Optional[Dict[str, float]] = None,
    beta_difficulty: float = BETA_DIFFICULTY,
    gamma_exam: float = GAMMA_NEAR_EXAM,
    exam_horizon_days: int = EXAM_HORIZON_DAYS,
) -> float:
    """weight = credits * cat_coef * (1 + beta * difficulty) + gamma * near_exam"""
    category_coefs = category_coefs or CATEGORY_COEFS
    today = today or date.today()

    credits = float(row.get("credits", 0) or 0)
    difficulty = float(row.get("difficulty", 0) or 0)
    cat = str(row.get("category", "")).strip()
    cat_coef = category_coefs.get(cat, 1.0)

    base = credits * cat_coef * (1.0 + beta_difficulty * difficulty)

    exam_date = _safe_parse_date(row.get("exam_date"))
    near_exam = 0.0
    if exam_date:
        days = (exam_date - today).days
        if days >= 0:
            near_exam = max(0.0, 1.0 - days / float(exam_horizon_days))
            near_exam *= gamma_exam

    return base + near_exam

def compute_weights(df: pd.DataFrame, today: Optional[date] = None) -> pd.Series:
    today = today or date.today()
    weights = {}
    for _, row in df.iterrows():
        name = str(row["course_name"]).strip()
        weights[name] = compute_course_weight(row, today=today)
    return pd.Series(weights)

# ---------------- A) 連續變數：分鐘分配最佳化 -------------------------------

def optimize_minutes(
    df: pd.DataFrame,
    total_minutes_today: int,
    min_minutes_per_course: int = 0,
    max_minutes_per_course: Optional[int] = None,
    round_to: int = 30,
    today: Optional[date] = None,
) -> pd.DataFrame:
    """
    最大化 Σ weight * minutes，並使 Σ minutes = total_minutes_today
    回傳 DataFrame: [minutes, weight, score]
    """
    weights = compute_weights(df, today=today)
    courses = list(weights.index)

    m = pulp.LpVariable.dicts("m", courses, lowBound=0, cat="Continuous")
    prob = pulp.LpProblem("StudyMinutesAllocation", pulp.LpMaximize)

    prob += pulp.lpSum([weights[c] * m[c] for c in courses])
    prob += pulp.lpSum([m[c] for c in courses]) == total_minutes_today, "TotalMinutes"

    for c in courses:
        prob += m[c] >= float(min_minutes_per_course), f"Min_{c}"
        if max_minutes_per_course is not None:
            prob += m[c] <= float(max_minutes_per_course), f"Max_{c}"

    prob.solve(pulp.PULP_CBC_CMD(msg=False))

    minutes = {c: max(0.0, m[c].value()) for c in courses}
    if round_to and round_to > 1:
        minutes = {c: round(minutes[c] / round_to) * round_to for c in courses}

    out = pd.DataFrame({"minutes": pd.Series(minutes), "weight": weights})
    out["score"] = out["minutes"] * out["weight"]
    out.sort_values("score", ascending=False, inplace=True)
    return out

# ---------------- B) 0/1 整數規劃：block 指派 -------------------------------

def make_blocks(start: datetime, end: datetime, block_minutes: int = 30) -> List[datetime]:
    blocks = []
    t = start
    delta = timedelta(minutes=block_minutes)
    while t + delta <= end:
        blocks.append(t)
        t += delta
    return blocks

def optimize_blocks(
    df: pd.DataFrame,
    blocks: List[datetime],
    min_blocks_per_course: int = 0,
    max_blocks_per_course: Optional[int] = None,
    today: Optional[date] = None,
) -> pd.DataFrame:
    """
    0/1 指派：每個 block 至多給一科；可設每科最小/最大 block 數
    回傳 DataFrame: [block_time, course_name]
    """
    weights = compute_weights(df, today=today)
    courses = list(weights.index)
    B = list(range(len(blocks)))

    x = pulp.LpVariable.dicts(
        "x", ((c, b) for c in courses for b in B), lowBound=0, upBound=1, cat="Binary"
    )
    prob = pulp.LpProblem("StudyBlockAssignment", pulp.LpMaximize)

    prob += pulp.lpSum(weights[c] * x[(c, b)] for c in courses for b in B)

    for b in B:
        prob += pulp.lpSum(x[(c, b)] for c in courses) <= 1, f"OneCoursePerBlock_{b}"

    for c in courses:
        if min_blocks_per_course:
            prob += pulp.lpSum(x[(c, b)] for b in B) >= float(min_blocks_per_course), f"MinBlocks_{c}"
        if max_blocks_per_course is not None:
            prob += pulp.lpSum(x[(c, b)] for b in B) <= float(max_blocks_per_course), f"MaxBlocks_{c}"

    prob.solve(pulp.PULP_CBC_CMD(msg=False))

    assigned: List[Tuple[datetime, str]] = []
    for c in courses:
        for b in B:
            val = x[(c, b)].value()
            if val is not None and val > 0.5:
                assigned.append((blocks[b], c))

    out = pd.DataFrame(assigned, columns=["block_time", "course_name"])
    out.sort_values(["block_time", "course_name"], inplace=True)
    return out

if __name__ == "__main__":
    # 範例：讀 data/courses_demo_weekly.csv 做測試
    df = pd.read_csv("data/courses_demo_weekly.csv", encoding="utf-8")

    plan_minutes = optimize_minutes(
        df,
        total_minutes_today=180,
        min_minutes_per_course=0,
        max_minutes_per_course=120,
        round_to=30,
    )
    print("=== 今日分鐘分配（四捨五入到 30 分鐘） ===")
    print(plan_minutes, "\n")

    today = datetime.now().date()
    blocks = make_blocks(
        start=datetime.combine(today, datetime.strptime("19:00", "%H:%M").time()),
        end=datetime.combine(today, datetime.strptime("22:00", "%H:%M").time()),
        block_minutes=30,
    )
    assign = optimize_blocks(df, blocks=blocks)
    print("=== Block 指派結果 ===")
    print(assign)
