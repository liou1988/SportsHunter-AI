from core.rating.engine import HunterRatingEngine
from features.models import FeatureVector


def rate_fixture(vector: FeatureVector):
    return HunterRatingEngine().score(vector)
