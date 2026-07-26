from __future__ import annotations

from pipeline.runner import PredictionPipeline


def main() -> None:
    for result in PredictionPipeline().run_today():
        print(result.to_dict())


if __name__ == "__main__":
    main()
