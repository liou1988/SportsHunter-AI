from __future__ import annotations

from dataclasses import dataclass
from math import floor

from datahub.models import Fixture, Odds, OddsMarket
from features.models import FeatureVector
from pipeline.models import HandicapPrediction, MarketPrediction, ScorePrediction, TotalGoalsPrediction


@dataclass(slots=True)
class ExpectedGoals:
    home: float
    away: float

    @property
    def total(self) -> float:
        return round(self.home + self.away, 2)

    @property
    def margin(self) -> float:
        return round(self.home - self.away, 2)


class MarketPredictionModel:
    """Rule-based market projection built from SportsHunter features."""

    def predict(self, fixture: Fixture, vector: FeatureVector, odds: list[Odds] | None = None) -> MarketPrediction:
        odds = odds or []
        expected = self._expected_goals(vector)
        score = self._score_prediction(expected)
        moneyline_pick, predicted_side = self._moneyline_pick(fixture, expected.margin)
        total_goals = self._total_goals_prediction(expected, odds)
        handicap = self._handicap_prediction(fixture, expected.margin)
        notes = self._notes(vector, expected)

        return MarketPrediction(
            predicted_side=predicted_side,
            moneyline_pick=moneyline_pick,
            score=score,
            total_goals=total_goals,
            handicap=handicap,
            notes=notes,
        )

    @staticmethod
    def _expected_goals(vector: FeatureVector) -> ExpectedGoals:
        home_form_edge = vector.get("home_recent_form") - vector.get("away_recent_form")
        elo_edge = vector.get("elo_difference") - 50
        market_edge = vector.get("market_heat") - 50
        momentum_edge = vector.get("live_momentum") - 50
        home_advantage = vector.get("home_advantage") - 50

        home_xg = 1.22
        home_xg += (vector.get("home_attack_index") - 50) * 0.018
        home_xg += (50 - vector.get("away_defense_index")) * 0.012
        home_xg += home_advantage * 0.010
        home_xg += elo_edge * 0.010
        home_xg += home_form_edge * 0.005
        home_xg += market_edge * 0.006
        home_xg += momentum_edge * 0.008
        home_xg -= vector.get("fatigue_index") * 0.003
        home_xg -= vector.get("injury_index") * 0.004

        away_xg = 1.04
        away_xg += (vector.get("away_attack_index") - 50) * 0.018
        away_xg += (50 - vector.get("home_defense_index")) * 0.012
        away_xg -= home_advantage * 0.004
        away_xg -= elo_edge * 0.008
        away_xg -= home_form_edge * 0.005
        away_xg -= momentum_edge * 0.006
        away_xg -= vector.get("fatigue_index") * 0.002
        away_xg -= vector.get("injury_index") * 0.002

        return ExpectedGoals(home=_clip(home_xg, 0.2, 4.5), away=_clip(away_xg, 0.2, 4.5))

    @staticmethod
    def _score_prediction(expected: ExpectedGoals) -> ScorePrediction:
        home_goals = _goal_count(expected.home)
        away_goals = _goal_count(expected.away)
        if expected.margin >= 0.35 and home_goals <= away_goals:
            home_goals = away_goals + 1
        elif expected.margin <= -0.35 and away_goals <= home_goals:
            away_goals = home_goals + 1
        elif abs(expected.margin) < 0.18 and home_goals != away_goals:
            lower = min(home_goals, away_goals)
            home_goals = lower
            away_goals = lower

        home_goals = min(home_goals, 6)
        away_goals = min(away_goals, 6)
        return ScorePrediction(
            home=home_goals,
            away=away_goals,
            expected_home_goals=expected.home,
            expected_away_goals=expected.away,
            text=f"{home_goals}-{away_goals}",
        )

    @staticmethod
    def _moneyline_pick(fixture: Fixture, margin: float) -> tuple[str, str | None]:
        if margin >= 0.18:
            return "HOME", fixture.home_team.name
        if margin <= -0.18:
            return "AWAY", fixture.away_team.name
        return "DRAW", None

    @staticmethod
    def _total_goals_prediction(expected: ExpectedGoals, odds: list[Odds]) -> TotalGoalsPrediction:
        totals = next((item for item in odds if item.market == OddsMarket.TOTALS and item.line is not None), None)
        line = float(totals.line) if totals and totals.line is not None else 2.5
        edge = expected.total - line
        if edge >= 0.15:
            pick = "OVER"
            label = f"大 {line:g}"
            reason = f"预期总进球 {expected.total:g} 高于盘口 {line:g}"
        elif edge <= -0.15:
            pick = "UNDER"
            label = f"小 {line:g}"
            reason = f"预期总进球 {expected.total:g} 低于盘口 {line:g}"
        else:
            pick = "NO_PLAY"
            label = f"大小球观望 {line:g}"
            reason = f"预期总进球 {expected.total:g} 接近盘口 {line:g}"

        return TotalGoalsPrediction(
            line=round(line, 2),
            pick=pick,
            label=label,
            expected_total=expected.total,
            confidence=_confidence_from_edge(abs(edge), base=0.50, scale=0.18),
            reason=reason,
        )

    @staticmethod
    def _handicap_prediction(fixture: Fixture, margin: float) -> HandicapPrediction:
        abs_margin = abs(margin)
        if abs_margin < 0.15:
            return HandicapPrediction(
                side=None,
                team=None,
                line=0.0,
                pick="NO_PLAY",
                label="让球观望",
                expected_margin=margin,
                confidence=0.5,
                reason=f"预期净胜球 {margin:g}，优势不足",
            )

        if margin > 0:
            side = "home"
            team = fixture.home_team.name
            side_label = "主队"
        else:
            side = "away"
            team = fixture.away_team.name
            side_label = "客队"

        line = _handicap_line(abs_margin)
        line_label = "平手" if line == 0 else f"{line:g}"
        return HandicapPrediction(
            side=side,
            team=team,
            line=line,
            pick=f"{side.upper()}_HANDICAP",
            label=f"{side_label} {line_label}",
            expected_margin=margin,
            confidence=_confidence_from_edge(abs_margin, base=0.52, scale=0.22),
            reason=f"{side_label}预期净胜球 {abs_margin:g}",
        )

    @staticmethod
    def _notes(vector: FeatureVector, expected: ExpectedGoals) -> list[str]:
        notes = [
            f"预期进球 {expected.home:g}-{expected.away:g}",
        ]
        if "odds_missing" in vector.warnings or "odds_unavailable" in vector.warnings:
            notes.append("赔率数据不足，大小球和让球为规则估算")
        if "statistics_unavailable" in vector.warnings:
            notes.append("赛前统计不足，比分预测已降低确定性")
        return notes


def _goal_count(expected_goals: float) -> int:
    return max(0, int(floor(expected_goals + 0.45)))


def _handicap_line(abs_margin: float) -> float:
    if abs_margin < 0.35:
        return 0.0
    if abs_margin < 0.70:
        return -0.25
    if abs_margin < 1.05:
        return -0.5
    if abs_margin < 1.40:
        return -0.75
    return -1.0


def _confidence_from_edge(edge: float, base: float, scale: float) -> float:
    return round(_clip(base + edge * scale, 0.5, 0.9), 2)


def _clip(value: float, low: float, high: float) -> float:
    return round(max(low, min(high, value)), 2)
