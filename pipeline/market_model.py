from __future__ import annotations

from dataclasses import dataclass
from math import exp, factorial

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
        handicap = self._handicap_prediction(fixture, expected.margin, odds)
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
        fatigue_pressure = max(0.0, vector.get("fatigue_index") - 50)
        injury_pressure = max(0.0, vector.get("injury_index") - 50)

        home_xg = 1.22
        home_xg += (vector.get("home_attack_index") - 50) * 0.018
        home_xg += (50 - vector.get("away_defense_index")) * 0.012
        home_xg += home_advantage * 0.010
        home_xg += elo_edge * 0.010
        home_xg += home_form_edge * 0.005
        home_xg += market_edge * 0.006
        home_xg += momentum_edge * 0.008
        home_xg -= fatigue_pressure * 0.003
        home_xg -= injury_pressure * 0.004

        away_xg = 1.04
        away_xg += (vector.get("away_attack_index") - 50) * 0.018
        away_xg += (50 - vector.get("home_defense_index")) * 0.012
        away_xg -= home_advantage * 0.004
        away_xg -= elo_edge * 0.008
        away_xg -= home_form_edge * 0.005
        away_xg -= momentum_edge * 0.006
        away_xg -= fatigue_pressure * 0.002
        away_xg -= injury_pressure * 0.002

        return ExpectedGoals(home=_clip(home_xg, 0.2, 4.5), away=_clip(away_xg, 0.2, 4.5))

    @staticmethod
    def _score_prediction(expected: ExpectedGoals) -> ScorePrediction:
        home_goals, away_goals, alternatives = _most_likely_scores(expected)
        primary_text = f"{home_goals}-{away_goals}"
        display_scores = [primary_text, *alternatives[:2]]
        return ScorePrediction(
            home=home_goals,
            away=away_goals,
            expected_home_goals=expected.home,
            expected_away_goals=expected.away,
            text=" / ".join(display_scores),
            alternatives=alternatives,
        )

    @staticmethod
    def _moneyline_pick(fixture: Fixture, margin: float) -> tuple[str, str | None]:
        if margin >= 0.28:
            return "HOME", fixture.home_team.name
        if margin <= -0.28:
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
            water_adjustment = _market_confidence_adjustment(totals.over if totals else None, totals.under if totals else None)
        elif edge <= -0.15:
            pick = "UNDER"
            label = f"小 {line:g}"
            reason = f"预期总进球 {expected.total:g} 低于盘口 {line:g}"
            water_adjustment = _market_confidence_adjustment(totals.under if totals else None, totals.over if totals else None)
        else:
            pick = "NO_PLAY"
            label = f"大小球观望 {line:g}"
            reason = f"预期总进球 {expected.total:g} 接近盘口 {line:g}"
            water_adjustment = 0.0

        if totals is not None and totals.over is not None and totals.under is not None:
            reason = f"{reason}，水位 大 {totals.over:g} / 小 {totals.under:g}"

        return TotalGoalsPrediction(
            line=round(line, 2),
            pick=pick,
            label=label,
            expected_total=expected.total,
            confidence=_confidence_from_edge(abs(edge), base=0.50 + water_adjustment, scale=0.18),
            reason=reason,
            edge=round(edge, 2),
            bookmaker=totals.bookmaker if totals else None,
            over_odds=totals.over if totals else None,
            under_odds=totals.under if totals else None,
            market_available=totals is not None,
        )

    @staticmethod
    def _handicap_prediction(fixture: Fixture, margin: float, odds: list[Odds]) -> HandicapPrediction:
        handicap = next((item for item in odds if item.market == OddsMarket.ASIAN_HANDICAP and item.line is not None), None)
        if handicap is not None and handicap.line is not None:
            home_line = float(handicap.line)
            away_line = -home_line
            home_cover_edge = margin + home_line
            away_cover_edge = -margin + away_line
            if max(home_cover_edge, away_cover_edge) < 0.10:
                return HandicapPrediction(
                    side=None,
                    team=None,
                    line=round(home_line, 2),
                    pick="NO_PLAY",
                    label=f"让球观望（主队 {home_line:g}）",
                    expected_margin=margin,
                    confidence=0.5,
                    reason=f"预期净胜球 {margin:g} 接近真实盘口 {home_line:g}",
                    edge=round(max(home_cover_edge, away_cover_edge), 2),
                    bookmaker=handicap.bookmaker,
                    home_odds=handicap.home,
                    away_odds=handicap.away,
                    market_available=True,
                )

            if home_cover_edge >= away_cover_edge:
                side = "home"
                team = fixture.home_team.name
                line = home_line
                edge = home_cover_edge
                side_label = "主队"
                water_adjustment = _market_confidence_adjustment(handicap.home, handicap.away)
            else:
                side = "away"
                team = fixture.away_team.name
                line = away_line
                edge = away_cover_edge
                side_label = "客队"
                water_adjustment = _market_confidence_adjustment(handicap.away, handicap.home)

            line_label = "平手" if line == 0 else f"{line:g}"
            reason = f"{side_label}预期盘口优势 {edge:g}，真实主队盘口 {home_line:g}"
            if handicap.home is not None and handicap.away is not None:
                reason = f"{reason}，水位 主 {handicap.home:g} / 客 {handicap.away:g}"
            return HandicapPrediction(
                side=side,
                team=team,
                line=round(line, 2),
                pick=f"{side.upper()}_HANDICAP",
                label=f"{side_label} {line_label}",
                expected_margin=margin,
                confidence=_confidence_from_edge(abs(edge), base=0.52 + water_adjustment, scale=0.24),
                reason=reason,
                edge=round(edge, 2),
                bookmaker=handicap.bookmaker,
                home_odds=handicap.home,
                away_odds=handicap.away,
                market_available=True,
            )

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
                edge=round(abs_margin, 2),
                market_available=False,
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
            edge=round(abs_margin, 2),
            market_available=False,
        )

    @staticmethod
    def _notes(vector: FeatureVector, expected: ExpectedGoals) -> list[str]:
        notes = [
            f"预期进球 {expected.home:g}-{expected.away:g}",
        ]
        if "odds_missing" in vector.warnings or "odds_unavailable" in vector.warnings:
            notes.append("盘口数据不足时，大小球和让球使用规则估算")
        if "statistics_unavailable" in vector.warnings:
            notes.append("赛前统计不足，比分预测已降低确定性")
        return notes


def _most_likely_scores(expected: ExpectedGoals) -> tuple[int, int, list[str]]:
    target_total = _target_total_goals(expected.total)
    candidates: list[tuple[float, int, int]] = []
    for home_goals in range(0, 6):
        for away_goals in range(0, 6):
            total = home_goals + away_goals
            margin = home_goals - away_goals
            probability = _poisson_probability(home_goals, expected.home) * _poisson_probability(away_goals, expected.away)
            total_penalty = abs(total - target_total) * 0.012
            margin_penalty = abs(margin - expected.margin) * 0.018
            stale_bias_penalty = 0.006 if (home_goals, away_goals) == (2, 1) and expected.margin < 0.55 else 0.0
            candidates.append((probability - total_penalty - margin_penalty - stale_bias_penalty, home_goals, away_goals))

    ranked = sorted(
        candidates,
        key=lambda item: (item[0], -abs((item[1] - item[2]) - expected.margin), -item[1] - item[2]),
        reverse=True,
    )
    _, home_goals, away_goals = ranked[0]
    primary = (home_goals, away_goals)
    alternatives: list[str] = []
    for _, alt_home, alt_away in ranked[1:]:
        if (alt_home, alt_away) == primary:
            continue
        if abs((alt_home + alt_away) - target_total) > 1:
            continue
        if abs((alt_home - alt_away) - expected.margin) > 2.0:
            continue
        text = f"{alt_home}-{alt_away}"
        if text not in alternatives:
            alternatives.append(text)
        if len(alternatives) >= 2:
            break
    return home_goals, away_goals, alternatives


def _target_total_goals(total_xg: float) -> int:
    if total_xg < 1.75:
        return 1
    if total_xg < 2.25:
        return 2
    if total_xg < 2.85:
        return 3
    if total_xg < 3.55:
        return 4
    return 5


def _poisson_probability(goals: int, expected_goals: float) -> float:
    return exp(-expected_goals) * (expected_goals ** goals) / factorial(goals)


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


def _market_confidence_adjustment(selected_odds: float | None, opposite_odds: float | None) -> float:
    selected_probability = _implied_probability(selected_odds)
    opposite_probability = _implied_probability(opposite_odds)
    if selected_probability is None or opposite_probability is None:
        return 0.0
    diff = selected_probability - opposite_probability
    if diff >= 0.06:
        return 0.03
    if diff <= -0.06:
        return -0.03
    return 0.0


def _implied_probability(odds: float | None) -> float | None:
    if odds is None or odds == 0:
        return None
    if odds < 0:
        return abs(odds) / (abs(odds) + 100)
    if odds >= 100:
        return 100 / (odds + 100)
    return 1 / odds


def _clip(value: float, low: float, high: float) -> float:
    return round(max(low, min(high, value)), 2)
