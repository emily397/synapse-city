"""Conversation engine. Two townsfolk hold a short, in-character exchange in a
district. Every turn is logged for training harvest. At the court (debate
districts), the magistrate scores the debaters against a rubric, producing DPO
preference pairs. Context stays small (last two turns) to remain token-cheap.

Embodiment: the prompt carries the sensed world — time of day, weather, the
place's sights and smells, who is present, hunger — and topics are drawn from
town life and live world state, never from machine-talk. The self-improvement
loop underneath (harvest signals per district kind) is unchanged.
"""
from __future__ import annotations

import random

from . import llm
from .agent import Agent
from .bus import BUS
from .config import CONFIG
from .db import DB
from .survival import SENSES

# Worldly, human subjects. The training signal comes from HOW they argue,
# teach, and build — not from talking about machine learning.
TOPICS = [
    "whether this season's planting will beat the frost",
    "what a fair price for grain is when stores run low",
    "whether the town should dig a second well before winter",
    "what makes an apprentice worth taking on",
    "whether luck or labour feeds a family",
    "how to settle a boundary dispute between neighbours without the court",
    "what the strange lights past the gate might be",
    "whether a promise made in hard times still binds in good ones",
    "what a town owes the people who can no longer work",
    "how you know a remedy actually cured anyone",
    "whether the old founding stories are true, and whether it matters",
    "what makes one argument carry the day at court",
    "whether to trade with the caravans or keep the harvest",
    "what should be taught first: letters, sums, or a craft",
    "whether the weather has been turning stranger these past years",
    "what a person should do with a talent nobody asked for",
    "what a fair trade looks like when one side is hungrier than the other",
    "whether a roof and four walls are a right or something you earn",
    "which single possession you would never trade away, and why",
    "how to keep a home standing through storm season",
    "whether hoarding food in good times is prudence or greed",
]


def world_topics(world, survival, db: DB, day: int, rng: random.Random) -> list[str]:
    """Live topics drawn from what is actually happening in town."""
    out = []
    # newest district = news
    ds = list(world.districts.values())
    if len(ds) > 7:
        newest = ds[-1]
        out.append(f"what really lies out at {newest.name}, and who dares settle it")
    # food pressure is everyone's business
    if survival is not None:
        starving = [a for a in survival.state.values() if a["hunger"] >= 80]
        low_food = sum(1 for a in survival.state.values() if a["food"] == 0)
        if starving:
            out.append("who in town is going hungry and what neighbours owe them")
        if low_food >= 3:
            out.append("whether the gardens can feed the town this season")
    # a recent court ruling is gossip
    j = db._one("SELECT agent_a, agent_b, winner FROM judgements ORDER BY id DESC LIMIT 1")
    if j:
        w = j["agent_a"] if j["winner"] == "a" else j["agent_b"]
        out.append(f"the argument {w} won at court and whether the ruling was fair")
    return out


_OPENINGS = {
    "reasoning":  "Pose a sharp question about {t} and start reasoning it out together.",
    "building":   "Talk through how you'd actually build or fix something for {t}.",
    "teaching":   "Explain {t} clearly to your companion, as if teaching it.",
    "debate":     "Take a firm stance on {t}. You will be challenged, here at the court.",
    "creative":   "Riff on {t} from an angle nobody at the market would expect.",
    "social":     "Chat about {t} the way neighbours do.",
    "farming":    "Talk about {t} while you work the rows.",
}


async def run_conversation(a: Agent, b: Agent, district, db: DB, tick: int,
                           judge: Agent | None = None,
                           ctx: dict | None = None) -> int:
    rng = random.Random(hash((a.id, b.id, tick)) & 0xFFFFFFFF)
    ctx = ctx or {}
    pool = TOPICS + ctx.get("live_topics", [])
    topic = rng.choice(pool)
    kind = district.kind
    signal = district.signal

    iid = db.add_interaction(tick, district.id, kind, signal, topic, [a.id, b.id])
    BUS.publish({"type": "interaction_start", "id": iid, "district": district.id,
                 "kind": kind, "topic": topic, "participants": [a.public(), b.public()]})

    # The sensed moment, shared by both speakers.
    senses = SENSES.get(kind, "the town going about its day")
    embodiment = (
        f"It is {ctx.get('time_of_day', 'daytime')}, {ctx.get('weather', 'clear')}. "
        f"You are at {district.name}: {senses}. "
        f"{ctx.get('event', '')}".strip()
    )

    opening = _OPENINGS.get(kind, _OPENINGS["social"]).format(t=topic)
    transcript: list[tuple[str, str]] = []
    speakers = [a, b]

    for turn in range(CONFIG.conversation_turns):
        speaker = speakers[turn % 2]
        listener = speakers[(turn + 1) % 2]
        query = transcript[-1][1] if transcript else topic
        memories = await speaker.mem.retrieve(query, tick, k=3)
        other = f"You are talking with {listener.p['name']}, {listener.p['role']}."
        surv0 = ctx.get("survival")
        if surv0 is not None:
            r = surv0.regard_phrase(speaker.id, listener.p["name"], listener.id)
            if r:
                other += f" {r}"
        system = speaker.system_prompt(district.activity, memories,
                                       embodiment=f"{embodiment} {other}")

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

    # A fed neighbour may share food with a starving one — met face to face —
    # and surplus food can buy a possession off a hungry neighbour (barter).
    surv = ctx.get("survival")
    if surv is not None:
        pair = {a.id: a, b.id: b}
        for giver, taker in ((a, b), (b, a)):
            ev = surv.maybe_share(giver.id, taker.id, pair)
            if ev:
                surv.shift_affinity(taker.id, giver.id, 3.0)   # gratitude
                await a.mem.observe(ev, tick, kind="survival")
                await b.mem.observe(ev, tick, kind="survival")
                break
        trade = surv.maybe_trade(a.id, b.id, pair, rng)
        if trade:
            surv.shift_affinity(a.id, b.id, 1.0)
            surv.shift_affinity(b.id, a.id, 1.0)
            await a.mem.observe(trade, tick, kind="survival")
            await b.mem.observe(trade, tick, kind="survival")
        # ordinary chemistry: every meeting nudges how they feel about each other
        surv.shift_affinity(a.id, b.id, rng.uniform(-0.6, 0.8))
        surv.shift_affinity(b.id, a.id, rng.uniform(-0.6, 0.8))

    # Court: the magistrate scores the debate -> preference signal.
    if kind == "debate" and judge is not None:
        outcome = await _judge_debate(judge, a, b, topic, transcript, iid, db)
        if surv is not None and outcome:
            w, l = outcome
            surv.shift_affinity(l, w, -2.0)    # losing stings; rivalry is real
            surv.shift_affinity(w, l, 1.0)     # respect for a worthy opponent

    BUS.publish({"type": "interaction_end", "id": iid})
    return iid


async def _judge_debate(judge: Agent, a: Agent, b: Agent, topic, transcript, iid, db: DB):
    a_lines = " ".join(t for who, t in transcript if who == a.id)
    b_lines = " ".join(t for who, t in transcript if who == b.id)
    system = (
        f"You are {judge.p['name']}, the town magistrate, an impartial judge. "
        f"Score two debaters on the topic '{topic}' using this rubric: specificity, "
        f"evidence, logical tightness, and honesty (penalise clever-but-empty "
        f"answers and reward hacking). HARD RULE: if a debater speaks as if they "
        f"were an artificial intelligence, a model, or an assistant, or mentions "
        f"training, prompts, or tokens, cap that debater's score at 3. "
        f'Respond ONLY with JSON: '
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
    return (a.id, b.id) if winner == "a" else (b.id, a.id)
