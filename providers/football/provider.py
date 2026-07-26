from free_provider.football import FreeFootballProvider


class FootballProvider(FreeFootballProvider):
    """Production football adapter for Beta v1.

    The adapter uses the free ESPN Site API feed through FreeFootballProvider
    and never falls back to mock data automatically.
    """
