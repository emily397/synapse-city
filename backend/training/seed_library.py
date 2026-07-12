"""Seed the Town Library with foundational knowledge the residents can retrieve
into their conversations and reasoning: scripture, evolution, physics, and the
craft of building software. Distilled to standalone, embeddable notes (claim +
source), phrased as timeless wisdom a thoughtful townsperson might have read in
an old book — so it enriches their thinking without breaking the fiction.

    python seed_library.py        # idempotent: skips notes already present
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from synapse.config import CONFIG                       # noqa: E402
CONFIG.llm_backend = "ollama"
from synapse.db import DB                               # noqa: E402
from synapse.library import Library                     # noqa: E402

# (source_book, claim) — claims kept concise and worldly-useful.
NOTES = [
    # --- Scripture / moral philosophy ---
    ("the old scripture", "Do unto others as you would have them do unto you; the measure you give is the measure you get back."),
    ("the old scripture", "Pride goes before destruction, and a haughty spirit before a fall."),
    ("the old scripture", "A soft answer turns away wrath, but a harsh word stirs up anger."),
    ("the old scripture", "There is a time to sow and a time to reap; wisdom is knowing which season you are in."),
    ("the old scripture", "Faith, hope, and love endure, and the greatest of these is love."),
    ("the book of proverbs", "Go to the ant, consider her ways, and be wise: she stores in summer against the winter."),
    # --- Darwin / evolution ---
    ("Darwin, On the Origin of Species", "It is not the strongest that survives, nor the most intelligent, but the one most responsive to change."),
    ("Darwin, On the Origin of Species", "Small inherited variations, selected over many generations, accumulate into wholly new forms."),
    ("Darwin, On the Origin of Species", "Every creature is in a struggle for existence; those best suited to their conditions leave the most offspring."),
    ("on natural selection", "Traits that help a being survive and reproduce become more common; traits that hinder it fade away."),
    ("on natural selection", "Diversity is strength: a varied population weathers a changing world better than a uniform one."),
    # --- Einstein / physics ---
    ("Einstein, on relativity", "Space and time are not fixed stages but bend with motion and mass; the observer's frame changes what is measured."),
    ("Einstein, on relativity", "Energy and mass are two forms of one thing; a tiny mass holds enormous energy."),
    ("Einstein, in his letters", "Imagination is more important than knowledge, for knowledge is limited and imagination encircles the world."),
    ("Einstein, in his letters", "A theory should be as simple as possible, but no simpler."),
    ("on the quantum", "At the smallest scale the world is grainy and uncertain; one cannot know a particle's exact place and speed at once."),
    ("on the quantum", "A thing can hold many possibilities at once until it is observed, and only then settle into one."),
    ("on the quantum", "Distant things once joined can stay linked, so measuring one tells you of the other, however far apart."),
    # --- Computation / logic ---
    ("on reckoning engines", "Any calculation, however complex, can be built from simple steps repeated: read, decide, change, repeat."),
    ("on reckoning engines", "A machine that follows rules can imitate any other rule-following machine, given enough time and paper."),
    ("on logic", "From true premises, valid steps preserve truth; a single false step can corrupt the whole conclusion."),
    ("on logic", "To debug a fault, isolate one variable at a time; change nothing else until you know what moved."),
    # --- Software / building things ---
    ("the builder's handbook", "Make it work, make it right, make it fast, in that order; premature polish wastes the most labour."),
    ("the builder's handbook", "Name things plainly; a clear name saves more time than a clever trick."),
    ("the builder's handbook", "Small pieces that each do one thing well combine into systems you can actually fix."),
    ("the builder's handbook", "Test the thing by using it, not by admiring the plan; reality is the only honest judge."),
    ("the builder's handbook", "Write down what you learned so the next person, even your future self, need not learn it twice."),
    ("on making tools", "A good tool disappears in the hand; if people must think about the tool, it is not finished."),
    ("on making tools", "Measure before you optimise; most of the cost hides in one place you did not expect."),
]


async def main():
    db = DB()
    lib = Library(db)
    existing = {r["claim"] for r in db._all("SELECT claim FROM library")}
    added = 0
    for src, claim in NOTES:
        if claim in existing:
            continue
        await lib.add_note("book", claim, src, day=0)
        added += 1
        print(f"  + [{src}] {claim[:60]}...")
    total = db._one("SELECT COUNT(*) AS n FROM library")["n"]
    print(f"\nseeded {added} book-notes; library now holds {total} entries")


if __name__ == "__main__":
    asyncio.run(main())
