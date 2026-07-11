"""Engine smoke test. Runs the town headless (mock brain) and asserts the whole
self-learning loop actually produces data. Run either way:

    python tests/test_engine.py        # prints PASS/FAIL
    pytest backend/tests               # if pytest is installed
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from synapse.config import CONFIG          # noqa: E402
from synapse.simulation import SIM         # noqa: E402


async def _run(ticks: int):
    CONFIG.tick_seconds = 0.0
    for _ in range(ticks):
        await SIM.step()
        if SIM.tick % CONFIG.harvest_interval == 0:
            await SIM._harvest()
        await asyncio.sleep(0.002)
    await asyncio.sleep(0.3)
    return SIM._stats()


def test_engine_produces_training_signal():
    stats = asyncio.run(_run(180))
    assert stats["interactions"] > 5, "agents should meet and talk"
    assert stats["exchanges"] > 20, "conversations should log training rows"
    assert stats["judgements"] > 0, "the Arena should judge debates"
    assert stats["generation"] > 0, "datasets should be harvested into generations"
    ratings = [e["rating"] for e in stats["elo"]]
    assert any(abs(r - 1000.0) > 0.1 for r in ratings), "ELO should move from debates"


if __name__ == "__main__":
    try:
        test_engine_produces_training_signal()
        print("PASS: engine produces interactions, judgements, datasets, and live ELO")
    except AssertionError as e:
        print(f"FAIL: {e}")
        sys.exit(1)
