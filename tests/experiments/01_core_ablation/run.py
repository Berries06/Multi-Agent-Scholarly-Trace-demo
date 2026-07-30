from pathlib import Path

from tests.experiments.framework import cli


if __name__ == "__main__":
    cli(Path(__file__).with_name("experiment.json"))
