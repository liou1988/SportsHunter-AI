from core.risk.engine import RiskEngine
from features.models import FeatureVector


def evaluate_risk(vector: FeatureVector):
    return RiskEngine().evaluate(vector)
