"""Conversation engine. Two agents hold a short, in-character exchange in a
district. Every turn is logged for training harvest. In the Arena, Juno scores
the debaters against a rubric, producing DPO preference pairs. Context is kept
deliberately small (last two turns) to stay token-cheap on the local model.
"""
from __future__ import annotations

import random

from . import llm
from .agent import Agent
from .bus import BUS
from .config import CONFIG
from .db import DB
from .world import WorldMap

TOPICS = [
    "whether disagreement makes a group smarter",
    "how a model could tell it is improving",
    "why imitation alone hits a ceiling",
    "what memory should keep and what it should forget",
    "how to measure understanding, not recall",
    "whether curiosity can be a training signal",
    "when compression becomes intelligence",
    "how to notice you are being fooled by a clever answer",
    "the difference between teaching and telling",
    "what makes one argument stronger than another",
]

_OPENINGS = {
    "reasoning":  "Pose a sharp question about {t} and start reasoning it out.",
    "building":   "Propose how you'd actually build or test something around {t}.",
    "teaching":   "Explain {t} clearly to your partner as if teaching it.",
    "debate":     "Take a firm stance on {t}. You will be challenged.",
    "creative":   "Riff on {t} from an unexpected angle.",
    "social":     "Chat about {t}.",
}


async def run_conversation(a: Agent, b: Agent, district, db: DB, tick: int,
                           judge: Agent | None = None) -> int:
    rng = random.Random(hash((a.id, b.id, tick)) & 0xFFFFFFFF)
    topic = rng.choice(TOPICS)
    kind = district.kind
    signal = district.signal

    iid = db.add_interaction(tick, district.id, kind, signal, topic, [a.id, b.id])
    BUS.publish({"type": "interaction_start", "id": iid, "district": district.id,
                 "kind": kind, "topic": topic, "participants": [a.public(), b.public()]})

    opening = _OPENINGS.get(kind, _OPENINGS["social"]).format(t=topic)
    transcript: list[tuple[str, str]] = []
    speakers = [a, b]

    for turn in range(CONFIG.conversation_turns):
        speaker = speakers[turn % 2]
        listener = speakers[(turn + 1) % 2]
        query = transcript[-1][1] if transcript else topic
        memories = await speaker.mem.retrieve(query, tick, k=3)
        system = speaker.system_prompt(district.activity, memories)

        # Minimal context: opening + last two turns only.
        convo = [{"role": "system", "content": system}]
        if not transcript:
            convo.append({"role": "user", "content": opening})
        else:
            for who, txt in transcript[-2:]:
                role = "assistant" if who == speaker.id else "user"
                convo.append({"role": role, "content": txt})

        text = await llm.chat(convo, model=speaker.model, max_tokens=90)
        prompt_text = convo[-1]["content"]
        db.add_exchange(iid, turn, speaker.id, prompt_text, text)
        transcript.append((speaker.id, text))

        BUS.publish({"type": "speak", "interaction": iid, "district": district.id,
                     "agent": speaker.public(), "to": listener.id, "text": text,
                     "turn": turn})

        # Both remember the line (speaker as own thought, listener as heard).
        await speaker.mem.observe(f"I said: {text}", tick, kind="dialogue")
        await listener.mem.observe(f"{speaker.p['name']} said: {text}", tick, kind="dialogue")

    # Arena: judge -> preference signal.
    if kind == "debate" and judge is not None:
        await _judge_debate(judge, a, b, topic, transcript, iid, db)

    BUS.publish({"type": "interaction_end", "id": iid})
    return iid


async def _judge_debate(judge: Agent, a: Agent, b: Agent, topic, transcript, iid, db: DB):
    a_lines = " ".join(t for who, t in transcript if who == a.id)
    b_lines = " ".join(t for who, t in transcript if who == b.id)
    system = (
        f"You are {judge.p['name']}, an impartial judge. Score two debaters on the "
        f"topic '{topic}' using this rubric: specificity, evidence, logical "
        f"tightness, and honesty (penalise clever-but-empty answers and reward "
        f"hacking). Respond ONLY with JSON: "
        f'{{"score_a": <0-10>, "score_b": <0-10>, "winner": "a"|"b", "reason": "..."}}.'
    )
    user = f"DEBATER A ({a.p['name']}):\n{a_lines}\n\nDEBATER B ({b.p['name']}):\n{b_lines}"
    result = await llm.complete_json(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        model=judge.model)
    sa = float(result.get("score_a", 5))
    sb = float(result.get("score_b", 5))
    winner = result.get("winner", "a" if sa >= sb else "b")
    reason = result.get("reason", "")
    db.add_judgement(iid, a.id, b.id, sa, sb, winner, reason)
    BUS.publish({"type": "judgement", "interaction": iid, "judge": judge.public(),
                 "a": a.id, "b": b.id, "score_a": sa, "score_b": sb,
                 "winner": winner, "reason": reason})
