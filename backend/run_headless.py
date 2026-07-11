"""Run the town with no web layer and no GPU. Ticks fast, prints life, dumps
stats. Proves the whole engine (movement, conversation, judging, harvest, ELO)
end to end on any machine.

    python run_headless.py 40      # run 40 ticks
"""
import asyncio
import sys

from synapse.bus import BUS
from synapse.config import CONFIG
from synapse.simulation import SIM


async def main(ticks: int):
    CONFIG.tick_seconds = 0.0                 # go as fast as the CPU allows
    q = BUS.subscribe()

    async def printer():
        while True:
            ev = await q.get()
            t = ev.get("type")
            if t == "speak":
                a = ev["agent"]
                print(f"  [{a['name']:5}] {ev['text']}")
            elif t == "judgement":
                print(f"  ⚖️  {ev['a']} {ev['score_a']} vs {ev['b']} {ev['score_b']}"
                      f" -> {ev['winner']} wins")
            elif t == "reflect":
                print(f"  💭 {ev['agent']['name']}: {ev['insight']}")
            elif t == "generation":
                print(f"  📦 GEN {ev['generation']}: sft={ev['sft_count']} "
                      f"dpo={ev['dpo_count']} ({ev['note']})")
            elif t == "clock" and ev["minute"] == 0:
                print(f"--- Day {ev['day']} {ev['hour']:02d}:00 "
                      f"{'🌙' if ev['night'] else '☀️'} ---")

    pr = asyncio.create_task(printer())
    for _ in range(ticks):
        await SIM.step()
        if SIM.tick % CONFIG.harvest_interval == 0:
            await SIM._harvest()
        await asyncio.sleep(0.003)             # yield so conversation tasks run
    await asyncio.sleep(0.3)                   # drain the last conversations
    pr.cancel()

    print("\n=== FINAL STATS ===")
    print(SIM._stats())
    print("ELO:", {e["model"]: e["rating"] for e in SIM.db.get_elo()})


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    asyncio.run(main(n))
