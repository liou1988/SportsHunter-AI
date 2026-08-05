from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import exp, factorial
import re

from datahub.models import Fixture, FixtureStatus, Odds, OddsMarket
from features.models import FeatureVector
from pipeline.models import (
    HandicapPrediction,
    MarketPrediction,
    ScorePrediction,
    TotalGoalsPrediction,
)
from pipeline.probability import HistoricalProbabilityModel, LineProbability, ProbabilityProjection


PROBABILITY_EDGE_THRESHOLD = 0.04
NO_ODDS_PROBABILITY_THRESHOLD = 0.55


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
    """Market projection using historical probabilities with rule-based fallback."""

    def __init__(self, probability_model: HistoricalProbabilityModel | None = None) -> None:
        self.probability_model = probability_model

    def predict(
        self,
        fixture: Fixture,
        vector: FeatureVector,
        odds: list[Odds] | None = None,
    ) -> MarketPrediction:
        odds = odds or []
        rule_expected = self._expected_goals(vector)
        projection = self._probability_projection(fixture)
        if _fixture_score_floor(fixture) is not None:
            projection = None
        base_expected = (
            ExpectedGoals(projection.expected_home_goals, projection.expected_away_goals)
            if projection is not None
            else rule_expected
        )
        expected = self._market_adjusted_expected_goals(base_expected, odds, vector, projection)
        expected = self._live_adjusted_expected_goals(fixture, expected)
        score = self._score_prediction(fixture, expected, projection)
        moneyline_pick, predicted_side = self._moneyline_pick(fixture, expected.margin, projection)
        total_goals = self._total_goals_prediction(expected, odds, projection)
        handicap = self._handicap_prediction(fixture, expected.margin, odds, projection)
        notes = self._notes(vector, expected, projection)

        return MarketPrediction(
            predicted_side=predicted_side,
            moneyline_pick=moneyline_pick,
            score=score,
            total_goals=total_goals,
            handicap=handicap,
            notes=notes,
            probabilities=projection.outcomes.to_dict() if projection is not None else {},
            model_source=projection.source if projection is not None else "rule",
            sample_count=projection.sample_count if projection is not None else 0,
        )

    def _probability_projection(self, fixture: Fixture) -> ProbabilityProjection | None:
        if self.probability_model is None:
            return None
        try:
            return self.probability_model.predict(fixture)
        except Exception:  # noqa: BLE001 - market prediction must fall back to rules
            return None

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
    def _market_adjusted_expected_goals(
        expected: ExpectedGoals,
        odds: list[Odds],
        vector: FeatureVector,
        projection: ProbabilityProjection | None = None,
    ) -> ExpectedGoals:
        market_expected = _market_expected_goals(expected, odds)
        if market_expected is None:
            return expected
        weight = _market_expected_weight(vector, projection)
        return ExpectedGoals(
            home=_clip(expected.home * (1 - weight) + market_expected.home * weight, 0.2, 5.5),
            away=_clip(expected.away * (1 - weight) + market_expected.away * weight, 0.2, 5.5),
        )

    @staticmethod
    def _live_adjusted_expected_goals(fixture: Fixture, expected: ExpectedGoals) -> ExpectedGoals:
        floor = _fixture_score_floor(fixture)
        if floor is None:
            return expected
        min_home, min_away = floor
        remaining_ratio = _remaining_match_ratio(_live_elapsed_minutes(fixture))
        return ExpectedGoals(
            home=_clip(min_home + expected.home * remaining_ratio, min_home, min_home + 4.5),
            away=_clip(min_away + expected.away * remaining_ratio, min_away, min_away + 4.5),
        )

    @staticmethod
    def _score_prediction(
        fixture: Fixture,
        expected: ExpectedGoals,
        projection: ProbabilityProjection | None = None,
    ) -> ScorePrediction:
        score_floor = _fixture_score_floor(fixture)
        if projection is not None and score_floor is None:
            likely_scores = projection.most_likely_scores(3)
            if likely_scores:
                primary = likely_scores[0]
                alternatives = [score.text for score in likely_scores[1:]]
                return ScorePrediction(
                    home=primary.home,
                    away=primary.away,
                    expected_home_goals=expected.home,
                    expected_away_goals=expected.away,
                    text=" / ".join([primary.text, *alternatives]),
                    alternatives=alternatives,
                )

        min_home, min_away = score_floor or (0, 0)
        home_goals, away_goals, alternatives = _most_likely_scores(expected, min_home, min_away)
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
    def _moneyline_pick(
        fixture: Fixture,
        margin: float,
        projection: ProbabilityProjection | None = None,
    ) -> tuple[str, str | None]:
        if projection is not None:
            outcomes = [
                ("HOME", projection.outcomes.home, fixture.home_team.name),
                ("DRAW", projection.outcomes.draw, None),
                ("AWAY", projection.outcomes.away, fixture.away_team.name),
            ]
            pick, _, side = max(outcomes, key=lambda item: item[1])
            return pick, side

        if margin >= 0.28:
            return "HOME", fixture.home_team.name
        if margin <= -0.28:
            return "AWAY", fixture.away_team.name
        return "DRAW", None

    @staticmethod
    def _total_goals_prediction(
        expected: ExpectedGoals,
        odds: list[Odds],
        projection: ProbabilityProjection | None = None,
    ) -> TotalGoalsPrediction:
        totals = next(
            (item for item in odds if item.market == OddsMarket.TOTALS and item.line is not None),
            None,
        )
        line = float(totals.line) if totals and totals.line is not None else 2.5

        if projection is not None:
            over_probability = projection.total_goals_probability(line, "OVER")
            under_probability = projection.total_goals_probability(line, "UNDER")
            over_market = _no_vig_pair_probability(totals.over, totals.under) if totals else None
            under_market = _no_vig_pair_probability(totals.under, totals.over) if totals else None
            candidates = [
                _LineCandidate(
                    pick="OVER",
                    label=f"大 {line:g}",
                    probability=over_probability,
                    market_probability=over_market,
                    odds=totals.over if totals else None,
                ),
                _LineCandidate(
                    pick="UNDER",
                    label=f"小 {line:g}",
                    probability=under_probability,
                    market_probability=under_market,
                    odds=totals.under if totals else None,
                ),
            ]
            candidate = _best_line_candidate(candidates)
            model_probability = _effective_probability(candidate.probability)
            expected_value = _line_expected_value(candidate.probability, candidate.odds)
            edge = _candidate_edge(model_probability, candidate.market_probability)
            play_available = _is_probability_play(
                model_probability,
                candidate.market_probability,
                edge,
            )
            pick = candidate.pick if play_available else "NO_PLAY"
            label = candidate.label if play_available else f"大小球观望 {line:g}"
            reason = _probability_reason(
                candidate.pick,
                model_probability,
                candidate.market_probability,
                expected_value,
            )
            if not play_available:
                reason = f"{reason}，优势未达到出手阈值"

            return TotalGoalsPrediction(
                line=round(line, 2),
                pick=pick,
                label=label,
                expected_total=expected.total,
                confidence=_confidence_from_probability_edge(abs(edge)) if play_available else 0.5,
                reason=reason,
                edge=round(edge, 4),
                bookmaker=totals.bookmaker if totals else None,
                over_odds=totals.over if totals else None,
                under_odds=totals.under if totals else None,
                market_available=totals is not None,
                model_probability=round(model_probability, 4),
                market_probability=_round_optional(candidate.market_probability),
                expected_value=expected_value,
            )

        edge = expected.total - line
        if edge >= 0.15:
            pick = "OVER"
            label = f"大 {line:g}"
            reason = f"预期总进球 {expected.total:g} 高于盘口 {line:g}"
            water_adjustment = _market_confidence_adjustment(
                totals.over if totals else None,
                totals.under if totals else None,
            )
        elif edge <= -0.15:
            pick = "UNDER"
            label = f"小 {line:g}"
            reason = f"预期总进球 {expected.total:g} 低于盘口 {line:g}"
            water_adjustment = _market_confidence_adjustment(
                totals.under if totals else None,
                totals.over if totals else None,
            )
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
    def _handicap_prediction(
        fixture: Fixture,
        margin: float,
        odds: list[Odds],
        projection: ProbabilityProjection | None = None,
    ) -> HandicapPrediction:
        handicap = next(
            (
                item
                for item in odds
                if item.market == OddsMarket.ASIAN_HANDICAP and item.line is not None
            ),
            None,
        )
        if handicap is not None and handicap.line is not None:
            home_line = float(handicap.line)
            away_line = -home_line

            if projection is not None:
                home_probability = projection.handicap_probability("home", home_line)
                away_probability = projection.handicap_probability("away", away_line)
                home_market = _no_vig_pair_probability(handicap.home, handicap.away)
                away_market = _no_vig_pair_probability(handicap.away, handicap.home)
                candidates = [
                    _HandicapCandidate(
                        side="home",
                        team=fixture.home_team.name,
                        line=home_line,
                        label_side="主队",
                        probability=home_probability,
                        market_probability=home_market,
                        odds=handicap.home,
                    ),
                    _HandicapCandidate(
                        side="away",
                        team=fixture.away_team.name,
                        line=away_line,
                        label_side="客队",
                        probability=away_probability,
                        market_probability=away_market,
                        odds=handicap.away,
                    ),
                ]
                candidate = _best_handicap_candidate(candidates)
                model_probability = _effective_probability(candidate.probability)
                expected_value = _line_expected_value(candidate.probability, candidate.odds)
                edge = _candidate_edge(model_probability, candidate.market_probability)
                play_available = _is_probability_play(
                    model_probability,
                    candidate.market_probability,
                    edge,
                )
                line_label = "平手" if candidate.line == 0 else f"{candidate.line:g}"
                pick = f"{candidate.side.upper()}_HANDICAP" if play_available else "NO_PLAY"
                label = (
                    f"{candidate.label_side} {line_label}"
                    if play_available
                    else f"让球观望（主队 {home_line:g}）"
                )
                reason = _probability_reason(
                    candidate.label_side,
                    model_probability,
                    candidate.market_probability,
                    expected_value,
                )
                if not play_available:
                    reason = f"{reason}，优势未达到出手阈值"

                return HandicapPrediction(
                    side=candidate.side if play_available else None,
                    team=candidate.team if play_available else None,
                    line=round(candidate.line, 2),
                    pick=pick,
                    label=label,
                    expected_margin=margin,
                    confidence=(
                        _confidence_from_probability_edge(abs(edge)) if play_available else 0.5
                    ),
                    reason=reason,
                    edge=round(edge, 4),
                    bookmaker=handicap.bookmaker,
                    home_odds=handicap.home,
                    away_odds=handicap.away,
                    market_available=True,
                    model_probability=round(model_probability, 4),
                    market_probability=_round_optional(candidate.market_probability),
                    expected_value=expected_value,
                )

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
                confidence=_confidence_from_edge(
                    abs(edge),
                    base=0.52 + water_adjustment,
                    scale=0.24,
                ),
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
    def _notes(
        vector: FeatureVector,
        expected: ExpectedGoals,
        projection: ProbabilityProjection | None = None,
    ) -> list[str]:
        notes = [
            f"预期进球 {expected.home:g}-{expected.away:g}",
        ]
        if projection is not None:
            probabilities = projection.outcomes
            notes.append(
                "历史 Poisson "
                f"样本 {projection.sample_count} 场，主/平/客 "
                f"{_format_probability(probabilities.home)} / "
                f"{_format_probability(probabilities.draw)} / "
                f"{_format_probability(probabilities.away)}"
            )
        else:
            notes.append("历史样本不足，使用规则特征估算盘口")
        if "odds_missing" in vector.warnings or "odds_unavailable" in vector.warnings:
            notes.append("盘口数据不足时，大小球和让球使用模型估算")
        if "statistics_unavailable" in vector.warnings:
            notes.append("赛前统计不足，比分预测已降低确定性")
        return notes


@dataclass(slots=True)
class _LineCandidate:
    pick: str
    label: str
    probability: LineProbability
    market_probability: float | None
    odds: float | None


@dataclass(slots=True)
class _HandicapCandidate:
    side: str
    team: str
    line: float
    label_side: str
    probability: LineProbability
    market_probability: float | None
    odds: float | None


def _most_likely_scores(
    expected: ExpectedGoals,
    min_home_goals: int = 0,
    min_away_goals: int = 0,
) -> tuple[int, int, list[str]]:
    target_total = _target_total_goals(expected.total)
    candidates: list[tuple[float, int, int]] = []
    max_home_goals = max(5, min_home_goals + 5, int(expected.home) + 4)
    max_away_goals = max(5, min_away_goals + 5, int(expected.away) + 4)
    for home_goals in range(min_home_goals, max_home_goals + 1):
        for away_goals in range(min_away_goals, max_away_goals + 1):
            total = home_goals + away_goals
            margin = home_goals - away_goals
            probability = _poisson_probability(home_goals, expected.home) * _poisson_probability(
                away_goals,
                expected.away,
            )
            total_penalty = abs(total - target_total) * 0.012
            margin_penalty = abs(margin - expected.margin) * 0.018
            stale_bias_penalty = (
                0.006 if (home_goals, away_goals) == (2, 1) and expected.margin < 0.55 else 0.0
            )
            candidates.append(
                (
                    probability - total_penalty - margin_penalty - stale_bias_penalty,
                    home_goals,
                    away_goals,
                )
            )

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


def _best_line_candidate(candidates: list[_LineCandidate]) -> _LineCandidate:
    return max(
        candidates,
        key=lambda candidate: (
            _candidate_edge(
                _effective_probability(candidate.probability),
                candidate.market_probability,
            ),
            _line_expected_value(candidate.probability, candidate.odds) or -99.0,
            _effective_probability(candidate.probability),
        ),
    )


def _best_handicap_candidate(candidates: list[_HandicapCandidate]) -> _HandicapCandidate:
    return max(
        candidates,
        key=lambda candidate: (
            _candidate_edge(
                _effective_probability(candidate.probability),
                candidate.market_probability,
            ),
            _line_expected_value(candidate.probability, candidate.odds) or -99.0,
            _effective_probability(candidate.probability),
        ),
    )


def _market_expected_goals(expected: ExpectedGoals, odds: list[Odds]) -> ExpectedGoals | None:
    total = expected.total
    margin = expected.margin
    has_market_signal = False

    totals = next((item for item in odds if item.market == OddsMarket.TOTALS and item.line is not None), None)
    if totals is not None and totals.line is not None:
        total = float(totals.line)
        total_edge = _pair_probability_edge(totals.over, totals.under)
        if total_edge is not None:
            total += total_edge * 0.70
        has_market_signal = True

    handicap = next(
        (item for item in odds if item.market == OddsMarket.ASIAN_HANDICAP and item.line is not None),
        None,
    )
    if handicap is not None and handicap.line is not None:
        margin = -float(handicap.line)
        handicap_edge = _pair_probability_edge(handicap.home, handicap.away)
        if handicap_edge is not None:
            margin += handicap_edge * 0.55
        has_market_signal = True
    else:
        european = next(
            (
                item
                for item in odds
                if item.market == OddsMarket.EUROPEAN and item.home is not None and item.away is not None
            ),
            None,
        )
        probabilities = _no_vig_three_way_probabilities(european) if european else None
        if probabilities is not None:
            margin = (probabilities[0] - probabilities[2]) * 2.10
            has_market_signal = True

    if not has_market_signal:
        return None

    total = _clip(total, 1.1, 4.5)
    max_margin = max(0.2, total - 0.45)
    margin = _clip(margin, -max_margin, max_margin)
    return ExpectedGoals(
        home=_clip((total + margin) / 2, 0.2, 5.5),
        away=_clip((total - margin) / 2, 0.2, 5.5),
    )


def _market_expected_weight(
    vector: FeatureVector,
    projection: ProbabilityProjection | None,
) -> float:
    weight = 0.35
    if "statistics_unavailable" in vector.warnings:
        weight += 0.18
    if "standings_unavailable" in vector.warnings:
        weight += 0.08
    if projection is not None:
        relevant_team_samples = projection.home_team_sample_count + projection.away_team_sample_count
        if projection.source == "historical_league_poisson":
            weight -= 0.10
        if relevant_team_samples >= 6:
            weight -= 0.12
    return _clip(weight, 0.20, 0.70)


def _pair_probability_edge(selected_odds: float | None, opposite_odds: float | None) -> float | None:
    selected_probability = _no_vig_pair_probability(selected_odds, opposite_odds)
    opposite_probability = _no_vig_pair_probability(opposite_odds, selected_odds)
    if selected_probability is None or opposite_probability is None:
        return None
    return selected_probability - opposite_probability


def _no_vig_three_way_probabilities(odds: Odds | None) -> tuple[float, float, float] | None:
    if odds is None:
        return None
    home = _implied_probability(odds.home)
    draw = _implied_probability(odds.draw)
    away = _implied_probability(odds.away)
    if home is None or away is None:
        return None
    total = home + away + (draw or 0.0)
    if total <= 0:
        return None
    return home / total, (draw or 0.0) / total, away / total


def _fixture_score_floor(fixture: Fixture) -> tuple[int, int] | None:
    if fixture.status != FixtureStatus.LIVE or fixture.score is None:
        return None
    if fixture.score.home is None or fixture.score.away is None:
        return None
    return max(0, int(fixture.score.home)), max(0, int(fixture.score.away))


def _live_elapsed_minutes(fixture: Fixture) -> float | None:
    score = fixture.score
    texts = [
        getattr(score, "clock", None),
        getattr(score, "period", None),
    ]
    raw_status = {}
    if isinstance(fixture.raw, dict):
        raw_status = (
            fixture.raw.get("status")
            or ((fixture.raw.get("competitions") or [{}])[0].get("status") if fixture.raw.get("competitions") else {})
            or {}
        )
    status_type = raw_status.get("type") if isinstance(raw_status, dict) else {}
    if isinstance(status_type, dict):
        texts.extend([status_type.get("detail"), status_type.get("shortDetail"), status_type.get("description")])
    if isinstance(raw_status, dict):
        texts.append(raw_status.get("displayClock"))

    for text in texts:
        minute = _first_live_minute(text)
        if minute is not None:
            return minute

    start_time = _as_utc(getattr(fixture, "start_time", None))
    if start_time is not None:
        return _clip((datetime.now(timezone.utc) - start_time).total_seconds() / 60, 0.0, 130.0)
    return None


def _first_live_minute(value: object) -> float | None:
    if value in (None, ""):
        return None
    text = str(value)
    for match in re.finditer(r"\d{1,3}", text):
        minute = float(match.group(0))
        if 0 <= minute <= 130:
            return minute
    return None


def _remaining_match_ratio(elapsed_minutes: float | None) -> float:
    if elapsed_minutes is None:
        return 0.50
    return _clip((96.0 - elapsed_minutes) / 96.0, 0.06, 0.92)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _is_probability_play(
    model_probability: float,
    market_probability: float | None,
    edge: float,
) -> bool:
    if market_probability is None and model_probability < NO_ODDS_PROBABILITY_THRESHOLD:
        return False
    return edge >= PROBABILITY_EDGE_THRESHOLD


def _candidate_edge(model_probability: float, market_probability: float | None) -> float:
    baseline = market_probability if market_probability is not None else 0.5
    return model_probability - baseline


def _effective_probability(probability: LineProbability) -> float:
    return probability.win + probability.push * 0.5


def _line_expected_value(probability: LineProbability, odds: float | None) -> float | None:
    decimal_odds = _decimal_odds(odds)
    if decimal_odds is None:
        return None
    return round(probability.win * (decimal_odds - 1) - probability.lose, 4)


def _probability_reason(
    label: str,
    model_probability: float,
    market_probability: float | None,
    expected_value: float | None,
) -> str:
    reason = f"历史模型 {label} 概率 {_format_probability(model_probability)}"
    if market_probability is not None:
        reason = f"{reason}，去水市场概率 {_format_probability(market_probability)}"
    else:
        reason = f"{reason}，暂无完整盘口水位"
    if expected_value is not None:
        sign = "+" if expected_value >= 0 else ""
        reason = f"{reason}，EV {sign}{expected_value:.2%}"
    return reason


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


def _confidence_from_probability_edge(edge: float) -> float:
    return round(_clip(0.52 + edge * 3.0, 0.5, 0.9), 2)


def _market_confidence_adjustment(
    selected_odds: float | None,
    opposite_odds: float | None,
) -> float:
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


def _no_vig_pair_probability(
    selected_odds: float | None,
    opposite_odds: float | None,
) -> float | None:
    selected_probability = _implied_probability(selected_odds)
    opposite_probability = _implied_probability(opposite_odds)
    if selected_probability is None:
        return None
    if opposite_probability is None:
        return selected_probability
    total = selected_probability + opposite_probability
    return selected_probability / total if total else None


def _implied_probability(odds: float | None) -> float | None:
    if odds is None or odds == 0:
        return None
    if odds < 0:
        return abs(odds) / (abs(odds) + 100)
    if odds >= 100:
        return 100 / (odds + 100)
    return 1 / odds


def _decimal_odds(odds: float | None) -> float | None:
    if odds is None or odds == 0:
        return None
    if odds < 0:
        return 1 + 100 / abs(odds)
    if odds >= 100:
        return 1 + odds / 100
    return odds


def _format_probability(value: float) -> str:
    return f"{value:.1%}"


def _round_optional(value: float | None) -> float | None:
    return round(value, 4) if value is not None else None


def _clip(value: float, low: float, high: float) -> float:
    return round(max(low, min(high, value)), 2)
