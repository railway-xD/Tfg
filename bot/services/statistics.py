"""Cricket calculations shared by scoreboard, over summaries and final report."""

def overs_text(legal_balls: int) -> str:
    legal_balls = max(0, int(legal_balls or 0))
    return f"{legal_balls // 6}.{legal_balls % 6}"


def strike_rate(runs: int, balls: int) -> float:
    return (int(runs or 0) * 100.0 / int(balls)) if balls else 0.0


def economy(runs_conceded: int, legal_balls: int) -> float:
    return (int(runs_conceded or 0) * 6.0 / int(legal_balls)) if legal_balls else 0.0


def run_rate(runs: int, legal_balls: int) -> float:
    return (int(runs or 0) * 6.0 / int(legal_balls)) if legal_balls else 0.0


def extras_total(extras: dict | None) -> int:
    return sum(int(v or 0) for v in (extras or {}).values())


def innings_summary(innings: dict) -> dict:
    balls = int(innings.get("legal_balls", 0))
    runs = int(innings.get("runs", 0))
    return {
        "runs": runs,
        "wickets": int(innings.get("wickets", 0)),
        "overs": overs_text(balls),
        "run_rate": run_rate(runs, balls),
        "extras": extras_total(innings.get("extras")),
        "balls": balls,
    }
