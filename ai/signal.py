from core.rating.engine import HunterScore
from core.risk.models import RiskResult
from core.signal.engine import SignalEngine
from features.models import FeatureVector


def generate_signal(hunter_score: HunterScore, risk: RiskResult, vector: FeatureVector):
    return SignalEngine().generate(hunter_score, risk, vector)
