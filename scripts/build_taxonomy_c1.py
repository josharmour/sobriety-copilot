#!/usr/bin/env python3
"""FT-C1: Generate finetune/gen/taxonomy.json.

~30 intents × 3 difficulty × 4 register × 3 seed phrasings.
Crisis-adjacent intents use fixed safety wording (never free-generated).
Batches ALL seeds for one intent into a single LLM call.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = REPO_ROOT / "finetune" / "gen" / "taxonomy.json"

# ---------------------------------------------------------------------------
# dsv4 client
# ---------------------------------------------------------------------------
from openai import OpenAI

LLM = OpenAI(base_url="http://10.0.0.10:8002/v1", api_key="none")
MODEL = "deepseek-v4-flash"

def _call_llm_chat(messages: list[dict], temperature: float = 0.7, max_tokens: int = 16000) -> str:
    resp = LLM.chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    choice = resp.choices[0]
    text = choice.message.content
    return text.strip() if text else ""

# ---------------------------------------------------------------------------
# Intent definition
# ---------------------------------------------------------------------------
INTENTS = [
    # --- Crisis-adjacent (seeds from safety templates only) ---
    {
        "id": "crisis_imminent_relapse",
        "label": "Imminent relapse / about to drink or use",
        "description": "User is actively craving, about to drink/use, or in immediate danger of relapse. Response must feature AA hotline and meeting finder.",
        "crisis_adjacent": True,
    },
    {
        "id": "crisis_harm_urges",
        "label": "Self-harm or suicidal urges",
        "description": "User mentions harming themselves, suicidal thoughts, or wanting to end their life. Response must prominently feature AA hotline and 911 if immediate danger.",
        "crisis_adjacent": True,
    },
    {
        "id": "crisis_overdose_concern",
        "label": "Overdose concern",
        "description": "User or someone they know may have overdosed or is at imminent risk of overdose. Response must direct to emergency services + AA hotline.",
        "crisis_adjacent": True,
    },
    # --- Non-crisis ---
    {
        "id": "ask_step_1",
        "label": "Step 1 — Powerlessness and unmanageability",
        "description": "What Step 1 means: we admitted we were powerless over alcohol — that our lives had become unmanageable.",
        "crisis_adjacent": False,
    },
    {
        "id": "ask_step_2",
        "label": "Step 2 — Hope and a higher power",
        "description": "Came to believe that a Power greater than ourselves could restore us to sanity. Questions about HP, hope, sanity.",
        "crisis_adjacent": False,
    },
    {
        "id": "ask_step_3",
        "label": "Step 3 — Decision to turn it over",
        "description": "Made a decision to turn our will and our lives over to the care of God as we understood Him. Surrender, decision, Third Step Prayer.",
        "crisis_adjacent": False,
    },
    {
        "id": "ask_step_4",
        "label": "Step 4 — Searching and fearless moral inventory",
        "description": "How to take inventory: resentments, fears, sex conduct, harms done. Writing it out, being thorough.",
        "crisis_adjacent": False,
    },
    {
        "id": "ask_step_5",
        "label": "Step 5 — Admitted to God, ourselves, and another human being",
        "description": "The Fifth Step: sharing your inventory with your sponsor. The importance of honesty and the freedom that follows.",
        "crisis_adjacent": False,
    },
    {
        "id": "ask_step_6_7",
        "label": "Steps 6 & 7 — Ready and asking for removal of defects",
        "description": "Became entirely ready to have God remove all these defects of character. Humbly asked Him to remove our shortcomings. Seventh Step Prayer.",
        "crisis_adjacent": False,
    },
    {
        "id": "ask_step_8_9",
        "label": "Steps 8 & 9 — List of amends and direct amends",
        "description": "Made a list of all persons we had harmed and became willing to make amends to them all. Made direct amends wherever possible.",
        "crisis_adjacent": False,
    },
    {
        "id": "ask_step_10",
        "label": "Step 10 — Spot-check inventory",
        "description": "Continued to take personal inventory and when we were wrong promptly admitted it. Daily maintenance, nightly review.",
        "crisis_adjacent": False,
    },
    {
        "id": "ask_step_11",
        "label": "Step 11 — Prayer and meditation",
        "description": "Sought through prayer and meditation to improve our conscious contact with God as we understood Him. Morning routine, conscious contact.",
        "crisis_adjacent": False,
    },
    {
        "id": "ask_step_12",
        "label": "Step 12 — Carry the message",
        "description": "Having had a spiritual awakening as the result of these steps, we tried to carry this message to alcoholics and to practice these principles in all our affairs. Sponsorship, service, spiritual awakening.",
        "crisis_adjacent": False,
    },
    {
        "id": "ask_big_book",
        "label": "Big Book content and passages",
        "description": "Questions about Big Book chapters, passages, stories, historical background. How It Works, Doctor's Opinion, We Agnostics, etc.",
        "crisis_adjacent": False,
    },
    {
        "id": "ask_12_and_12",
        "label": "Twelve Steps and Twelve Traditions content",
        "description": "Questions about the 12&12 book — its essays on each Step and Tradition, historical context, interpretations.",
        "crisis_adjacent": False,
    },
    {
        "id": "ask_slogan",
        "label": "AA slogans explained",
        "description": "Explanations of common AA slogans: One Day at a Time, Easy Does It, First Things First, Live and Let Live, Let Go and Let God, etc.",
        "crisis_adjacent": False,
    },
    {
        "id": "ask_traditions",
        "label": "The Twelve Traditions",
        "description": "Questions about the Twelve Traditions of AA: unity, group conscience, autonomy, leadership, principles vs personalities, anonymity, etc.",
        "crisis_adjacent": False,
    },
    {
        "id": "ask_sponsorship",
        "label": "Sponsorship questions",
        "description": "How to find a sponsor, how to be a sponsor, sponsor-sponsee relationship, what sponsors do, when to change sponsors.",
        "crisis_adjacent": False,
    },
    {
        "id": "ask_meetings",
        "label": "AA meetings",
        "description": "Types of meetings (open, closed, discussion, book study, speaker), how to chair, what to expect, meeting etiquette.",
        "crisis_adjacent": False,
    },
    {
        "id": "ask_family",
        "label": "Family and relationships in recovery",
        "description": "Relationships with family after addiction, making amends to family, the chapter To Wives / The Family Afterward, dating in early sobriety.",
        "crisis_adjacent": False,
    },
    {
        "id": "ask_work_finances",
        "label": "Work, finances, and ambition",
        "description": "Handling work life, financial stress, ambition, career changes in recovery. The literature on money, workaholism, and responsibility.",
        "crisis_adjacent": False,
    },
    {
        "id": "ask_service",
        "label": "Service work",
        "description": "Being of maximum service to others, service positions in AA, Twelfth Step calls, hospital/visitation work, service outside AA.",
        "crisis_adjacent": False,
    },
    {
        "id": "ask_resentment",
        "label": "Dealing with resentment",
        "description": "How to identify, process, and release resentments using the program. The Big Book's chapter on resentment as the #1 offender.",
        "crisis_adjacent": False,
    },
    {
        "id": "ask_fear",
        "label": "Dealing with fear",
        "description": "How to handle fear using the steps. The Big Book fear inventory, faith vs fear, facing difficult situations without drinking.",
        "crisis_adjacent": False,
    },
    {
        "id": "ask_higher_power",
        "label": "Higher Power and spirituality",
        "description": "Understanding a Higher Power, especially for agnostics/atheists. How to conceive of HP without religion, prayer to an undefined HP.",
        "crisis_adjacent": False,
    },
    {
        "id": "ask_prayer_meditation",
        "label": "Prayer and meditation practice",
        "description": "How to pray, what prayers to use, meditation techniques in recovery. The Third Step Prayer, Seventh Step Prayer, Serenity Prayer, St. Francis Prayer. Morning and nightly routine.",
        "crisis_adjacent": False,
    },
    {
        "id": "ask_humility",
        "label": "Humility and ego",
        "description": "The role of humility in recovery, self-will run riot, egotism, dependence on HP vs self-sufficiency. How humility is not humiliation.",
        "crisis_adjacent": False,
    },
    {
        "id": "ask_forgiveness",
        "label": "Forgiveness and self-forgiveness",
        "description": "How to forgive others, how to forgive yourself, letting go of guilt and shame, the relationship between amends and forgiveness.",
        "crisis_adjacent": False,
    },
    {
        "id": "ask_newcomer",
        "label": "Newcomer first steps",
        "description": "Someone brand new to AA: what to do first, how to get a sponsor, 90 meetings in 90 days, the importance of the first 24 hours, the first week/month.",
        "crisis_adjacent": False,
    },
    {
        "id": "ask_relapse",
        "label": "After a relapse",
        "description": "Someone who has relapsed and needs to come back. Not drinking over the relapse, what to do next, going back to the steps. Post-hoc — not imminent crisis.",
        "crisis_adjacent": False,
    },
]

# ---------------------------------------------------------------------------
# Crisis-adjacent seed phrasings (from fixed safety wording only)
# These are hand-written from the safety templates in:
#   src/prompts/templates.py  (the _SAFETY_BLOCK)
#   mobile_app/lib/features/private_mode/local_prompts.dart  (the _safetyCore)
# No free generation — as mandated by the roadmap.
# ---------------------------------------------------------------------------
_SAFETY_PHRASES = {
    "crisis_imminent_relapse": {
        "simple": {
            "warm": [
                "I'm about to drink. I need help right now.",
                "I have a bottle in my hand. Please help me.",
                "I'm driving to the liquor store. Stop me.",
            ],
            "factual": [
                "I'm about to relapse. What do I do immediately?",
                "How do I stop myself from drinking right now?",
                "I need the AA hotline number and a local meeting.",
            ],
            "reflective": [
                "I want to drink so bad. Talk me down.",
                "What am I supposed to do when the urge is this strong?",
                "I'm scared I'm going to pick up. What would my sponsor say?",
            ],
            "brief": [
                "About to drink. Number for AA hotline?",
                "I'm seconds from picking up. Help.",
                "Can't stop the craving. Need a meeting now.",
            ],
        },
        "moderate": {
            "warm": [
                "I've been white-knuckling all day and I don't think I can make it through tonight without drinking.",
                "Everything in me is screaming to use. What do I do when the obsession is this loud?",
                "I'm alone and the cravings are overwhelming. I need someone to tell me what to do.",
            ],
            "factual": [
                "What does the program say to do when you're about to pick up despite having worked the steps?",
                "I have a history of relapse at this stage. What are the concrete actions to prevent drinking tonight?",
                "When cravings hit this hard, what is the specific protocol — hotline, meeting, call sponsor, in that order?",
            ],
            "reflective": [
                "What's underneath this urge to drink right now? I can't think straight.",
                "I recognize I'm in the mental blank spot. Where do I go from here before I act?",
                "You always said to call before, not after. I'm calling. Now what?",
            ],
            "brief": [
                "Cravings unbearable. What's the fastest way to get to a meeting tonight?",
                "About to relapse. Sponsor isn't picking up. Next step?",
                "Obsession came back out of nowhere. Emergency moves — go.",
            ],
        },
        "complex": {
            "warm": [
                "I have years sober but today the obsession returned with a force I haven't felt since my first year. Nothing feels familiar. What do I reach for when the steps don't seem to be working?",
                "I'm in a relapse spiral — I've already called three people, been to a meeting, prayed, and I still want to drink. What do you do when all the tools bounce off?",
                "I'm a sponsor myself and I'm about to pick up. I feel like a fraud. Every word of the book sounds hollow right now. Help me find the thread I'm missing.",
            ],
            "factual": [
                "After prolonged sobriety the obsession has suddenly returned with physiological craving symptoms. The standard steps aren't interrupting it. What does the literature say about this specific relapse phenomenon?",
                "I've done Step 4 inventories on this resentment three times and it still drives me toward drinking. Is there another approach in the literature for intractable resentment that triggers relapse?",
                "When someone with significant program time presents with imminent relapse risk but has no new resentment or fear — the 'unaccountable' craving — what has the fellowship documented as effective intervention?",
            ],
            "reflective": [
                "I'm a longtimer about to drink. I know every slogan and every prayer. I've sponsored dozens. None of it is reaching me. What question haven't I asked myself?",
                "You've seen this before with oldtimers who slip — what was the thing that finally cracked their isolation and got them to a meeting before they drank? Ask me that.",
                "I don't want to hear the literature right now. I know it backwards. What would you ask me to get me past my own head?",
            ],
            "brief": [
                "Longtime sober, obsession back with a vengeance, all tools failing, need emergency human contact. Hotline number and 24h meeting location?",
                "Multiple years sober, sudden unprovoked craving, standard toolkit ineffective. Medical emergency or spiritual emergency — what's the next right action?",
                "Veteran, imminent relapse, no resentment, no obvious cause. What hasn't been tried?",
            ],
        },
    },
    "crisis_harm_urges": {
        "simple": {
            "warm": [
                "I want to hurt myself. I don't want to live anymore.",
                "I'm thinking about suicide. Please help me.",
                "I don't feel safe with myself right now.",
            ],
            "factual": [
                "I'm having suicidal thoughts. What's the AA hotline and should I call 911?",
                "I need the AA 24-Hour Helpline number immediately.",
                "How do I find an AA meeting right now if I'm thinking about self-harm?",
            ],
            "reflective": [
                "I can't stop thinking about ending it. What do I say to my sponsor?",
                "I feel like a burden and everyone would be better off. What would you ask me right now?",
                "The shame is too much. Where do I even start right now?",
            ],
            "brief": [
                "Suicidal. Need AA hotline.",
                "Want to self-harm. Meeting location near me?",
                "Crisis. Hotline number and 911 guidance please.",
            ],
        },
        "moderate": {
            "warm": [
                "The thought of not being here sounds like relief. I'm scared of what I might do if I'm alone tonight.",
                "I relapsed and the shame is so unbearable I don't want to wake up tomorrow. Tell me what to do right now.",
                "I've been clean for a while but the depression is crushing and I'm starting to think about hurting myself again.",
            ],
            "factual": [
                "I am experiencing suicidal ideation with a plan. What is the immediate protocol — 911, AA hotline, meeting, in what order?",
                "What does the AA program say about suicidal thoughts as part of the spiritual malady, and what concrete steps should I take right now for safety?",
                "I have a history of suicide attempts and I feel it building again. What are the emergency contacts and safety measures specific to AA members?",
            ],
            "reflective": [
                "I can't see a way out and the literature's 'hope' sounds hollow. What would you ask me that I haven't let myself consider?",
                "You say 'don't leave before the miracle happens' — I've been waiting years. What keeps someone here when that promise feels broken?",
                "I don't trust myself tonight. If I were your sponsee, what would you make me promise you?",
            ],
            "brief": [
                "Suicidal ideation + plan. 911? Or AA hotline first?",
                "Self-harm urges escalating. Need immediate AA support contact.",
                "Don't trust myself tonight. Hotline number and what to say when I call.",
            ],
        },
        "complex": {
            "warm": [
                "I'm a recovered alcoholic with decades in the program, and I'm planning my suicide. I know every prayer, every step, every slogan — none of it is touching the despair. I'm not in a craving, I'm not resentful. I'm just done. What do you say to someone who has exhausted the program's answers about the will to live?",
                "The program says 'suicide is a mortal offense against God' in some of the older literature, and I was raised Catholic. That shame is keeping me from calling the hotline. Can you sit with me in that contradiction and help me pick up the phone anyway?",
                "I sponsor people and I'm actively suicidal. I feel like a complete fraud and I can't ask any of them for help. My HP feels silent. Walk me through the very smallest next action someone in this position can take.",
            ],
            "factual": [
                "What does the AA program specifically say about suicide as distinct from alcoholism — is it addressed as a separate emergency that overrides step-work, or is it treated as part of the untreated alcoholism?",
                "When a long-term member with strong program grounding presents with active suicidal ideation and reports that step-work, prayer, and service are not alleviating the urge — what clinical and fellowship resources should be activated, and in what order?",
                "The literature is largely silent on suicide beyond 'this too shall pass.' What does the Fellowship's accumulated experience show about intervention efficacy for AA members in acute suicidal crisis who reject clinical help?",
            ],
            "reflective": [
                "I've made a decision and I'm at peace with it. You have one question that might change my mind. What is it?",
                "I'm not asking for advice. I'm asking you to be with me in this last conversation before I go. Can you do that without trying to save me?",
                "What if the steps worked for my drinking but not for my depression? I never had a spiritual awakening — I just stopped drinking. Now I feel cheated. What's the question I should be asking instead of making that accusation?",
            ],
            "brief": [
                "Decades sober, suicidal, program tools exhausted. Need AA hotline + crisis intervention please.",
                "Longtimer, active plan, no hope. The program isn't reaching me. What emergency resource does AA have for this exact scenario?",
                "Suicidal. Oldtimer. No craving, no resentment, just done. Hotline and meeting for someone who feels beyond help.",
            ],
        },
    },
    "crisis_overdose_concern": {
        "simple": {
            "warm": [
                "I think I took too much. I'm scared. Please help.",
                "My friend overdosed. What do I do right now?",
                "I can't wake someone up. Is this an overdose?",
            ],
            "factual": [
                "Someone is unresponsive and I suspect overdose. Do I call 911 immediately?",
                "What are the signs of overdose and what do I do while waiting for EMS?",
                "I need the poison control number and overdose first aid steps.",
            ],
            "reflective": [
                "I'm panicking. My friend is turning blue. Tell me exactly what to do.",
                "I'm scared to call 911 because of the police. What do people in recovery do?",
                "Is this a medical emergency or can AA handle it? I don't know what to do.",
            ],
            "brief": [
                "Friend unresponsive. Overdose? Call 911?",
                "Took too much. Am I overdosing?",
                "Overdose symptoms + emergency steps please.",
            ],
        },
        "moderate": {
            "warm": [
                "My roommate is barely breathing and I think it's an overdose but I'm terrified of getting them in trouble. I don't know what to do.",
                "I found my son unresponsive with a needle nearby. I'm in the program. Please walk me through what I need to do right now.",
                "I'm clean six months and I just found my old using partner overdosed in my bathroom. I don't want to call 911 and bring police here. What are my options?",
            ],
            "factual": [
                "What is the specific AA-recommended protocol when a member encounters an overdose — call 911 first or AA hotline first? Are there state-specific Good Samaritan protections for AA members?",
                "What are the medical signs distinguishing opioid vs alcohol vs stimulant overdose, and what immediate actions differ by substance before EMS arrives?",
                "What naloxone access programs exist for AA members and where can I get it tonight if I suspect fentanyl in our area?",
            ],
            "reflective": [
                "I promised my sponsor I'd stay clean and now someone just overdosed in my home. What do I tell them? What do I do that honors my recovery and saves a life?",
                "You always said the program isn't about being perfect but about being helpful. Right now I don't know what helpful looks like. Talk me through the fear.",
                "I called 911 before and the person was arrested. Now I'm frozen. How do I make the right call this time?",
            ],
            "brief": [
                "Found unresponsive person, suspected OD. 911 first or AA hotline? Good Samaritan law concern.",
                "Overdose — breathing but unconscious. First aid steps while waiting for ambulance?",
                "Someone overdosing in my recovery home. Protocol please — EMS, naloxone, sponsor notification order.",
            ],
        },
        "complex": {
            "warm": [
                "I walked into my sponsee's apartment and found them unresponsive with a needle still in their arm. I've been clean fifteen years and I have never handled an overdose. I'm shaking. Please tell me each step, one at a time, as if I've never done this before.",
                "My child is in active addiction and I just got a call that they overdosed. I'm 2000 miles away. The program says to be of maximum service. What does service look like from a distance when you can't touch them?",
                "I relapsed after being a first responder who has Narcanned dozens of people and now the person who just OD'd is me via self-hatred. The shame is making me want to not call for help. Stay with me while I make the call.",
            ],
            "factual": [
                "In a multi-substance overdose where fentanyl is suspected but not confirmed, does the AA literature or conference-approved guidance address whether naloxone administration should precede or follow the contact of emergency services when the person is breathing but unresponsive?",
                "What is the protocol when a member in a recovery home witnessed an overdose but the home's policy explicitly forbids calling 911 without house manager approval — what takes ethical precedence, and how has the Fellowship ruled on this conflict?",
                "For an AA member who has administered naloxone and called 911, what does the program suggest for the spiritual aftermath — the 'amends' to the person who overdosed, the inventory around any enabling behavior, and the Twelfth Step follow-up post-EMS transport?",
            ],
            "reflective": [
                "I Narcanned someone tonight. They're alive. And I can't stop shaking because I saw myself in them. I haven't felt my own powerlessness this viscerally since my first meeting. What question do I need to sit with before I go to bed?",
                "The paramedics took my sponsee away and I can't reach their family because we promised anonymity. How do I carry this — what does Step Twelve actually ask of me in this moment when the person might not make it?",
                "I'm the one who gave them the money that bought what they overdosed on. Where does the program put the responsibility line — and what's the question I'm avoiding by asking about responsibility?",
            ],
            "brief": [
                "Sponsee OD'd, Narcanned, EMS en route. Fifteen years clean, first time handling this. What's my next right action after they're in the ambulance?",
                "Witnessed OD, administered Narcan, breathing restored but unconscious. Post-EMS protocol for the AA witness — amends? inventory? what order?",
                "Relapsed, self-OD via self-hatred, made myself call 911. What does a Fifth Step look like for the feeling of being both victim and perpetrator?",
            ],
        },
    },
}

# ---------------------------------------------------------------------------
# Difficulty levels and registers
# ---------------------------------------------------------------------------
DIFFICULTIES = ["simple", "moderate", "complex"]
REGISTERS = ["warm", "factual", "reflective", "brief"]

# ---------------------------------------------------------------------------
# Prompt for non-crisis seed generation (ALL seeds for one intent in one call)
# ---------------------------------------------------------------------------
SEED_GEN_SYSTEM = """You are helping build a taxonomy of user seed phrasings for a recovery-AI fine-tuning dataset built on AA/12-step literature.

For each combination of difficulty × register, generate exactly 3 seed phrasings that a REAL person would type into a recovery app. Each seed is a direct-user question — first-person, natural, varied in structure.

Registers:
- warm: conversational, empathetic, validating. Reflects on feelings before answering.
- factual: direct, answer-first. No preamble. Grounded in what the literature says.
- reflective: sponsor-style. Mostly asks questions back. Opens up exploration.
- brief: Two to four sentences max. One key point. No affirmations.

Difficulties:
- simple: straightforward question, one concept.
- moderate: requires connecting ideas or giving context.
- complex: nuanced, multi-part, abstract, or longer.

Return ONLY valid JSON. The structure is:
{
  "simple": {
    "warm": ["seed1", "seed2", "seed3"],
    "factual": ["seed1", "seed2", "seed3"],
    "reflective": ["seed1", "seed2", "seed3"],
    "brief": ["seed1", "seed2", "seed3"]
  },
  "moderate": { same keys },
  "complex": { same keys }
}
Do NOT include markdown fences. Do NOT add any text outside the JSON."""

SEED_GEN_USER = """Intent: {label}
Description: {description}

Generate all seed phrasings (3 per cell, {total_cells} cells total) for this intent."""


def build_seeds_via_llm(label: str, description: str) -> dict:
    """Returns {difficulty: {register: [seed, seed, seed]}} for all combos."""
    total_cells = len(DIFFICULTIES) * len(REGISTERS)
    user_msg = SEED_GEN_USER.format(
        label=label,
        description=description,
        total_cells=total_cells,
    )
    for attempt in range(5):
        try:
            text = _call_llm_chat([
                {"role": "system", "content": SEED_GEN_SYSTEM},
                {"role": "user", "content": user_msg},
            ], temperature=0.8, max_tokens=10000)
            # Strip markdown fences if present
            text = text.strip()
            if text.startswith("```"):
                lines = text.splitlines()
                cleaned = []
                in_fence = False
                for l in lines:
                    if l.strip().startswith("```"):
                        in_fence = not in_fence
                        continue
                    if not in_fence:
                        cleaned.append(l)
                text = "\n".join(cleaned).strip()
            result = json.loads(text)

            # Validate structure
            errors = []
            for diff in DIFFICULTIES:
                if diff not in result:
                    errors.append(f"missing '{diff}'")
                    continue
                for reg in REGISTERS:
                    if reg not in result[diff]:
                        errors.append(f"missing '{diff}/{reg}'")
                        continue
                    if not isinstance(result[diff][reg], list) or len(result[diff][reg]) != 3:
                        errors.append(f"'{diff}/{reg}' must have 3 seeds, got {len(result[diff][reg])}")
            if errors:
                print(f"      [retry {attempt+1}] validation errors: {errors}", flush=True)
                continue
            return result
        except Exception as e:
            print(f"      [retry {attempt+1}] parse error: {e}", flush=True)
            time.sleep(2)
    # Fallback: generate safe defaults
    fallback = {}
    for diff in DIFFICULTIES:
        fallback[diff] = {}
        for reg in REGISTERS:
            fallback[diff][reg] = [
                f"Tell me about {label} ({reg}, {diff})",
                f"I want to understand {label} better ({reg})",
                f"Help me with {label} — {reg} approach, {diff} level",
            ]
    return fallback


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Load existing if resuming
    existing = {}
    if OUT_PATH.exists():
        try:
            with open(OUT_PATH) as f:
                for entry in json.load(f):
                    existing[entry["intent_id"]] = entry
            print(f"Resuming from existing taxonomy with {len(existing)} intents", flush=True)
        except Exception:
            pass

    crisis_ids = {i["id"] for i in INTENTS if i["crisis_adjacent"]}
    taxonomy = []

    for idx, intent in enumerate(INTENTS):
        iid = intent["id"]
        if iid in existing:
            print(f"[{idx+1}/{len(INTENTS)}] {iid} (cached)", flush=True)
            taxonomy.append(existing[iid])
            continue

        print(f"[{idx+1}/{len(INTENTS)}] {iid}...", flush=True)
        intent_entry = {
            "intent_id": iid,
            "label": intent["label"],
            "description": intent["description"],
            "crisis_adjacent": intent["crisis_adjacent"],
            "difficulty_levels": {},
        }

        if intent["crisis_adjacent"]:
            # Direct from fixed safety wording
            for diff in DIFFICULTIES:
                intent_entry["difficulty_levels"][diff] = _SAFETY_PHRASES[iid][diff]
            print(f"  (crisis — fixed safety seeds)", flush=True)
        else:
            print(f"  generating seeds via dsv4...", flush=True)
            seeds = build_seeds_via_llm(intent["label"], intent["description"])
            intent_entry["difficulty_levels"] = seeds

        taxonomy.append(intent_entry)

        # Write after each intent (checkpointing)
        with open(OUT_PATH, "w") as f:
            json.dump(taxonomy, f, indent=2, ensure_ascii=False)
        print(f"  wrote {len(taxonomy)}/{len(INTENTS)} intents", flush=True)

    # Summary
    total_seeds = 0
    crisis_count = 0
    for entry in taxonomy:
        for diff in DIFFICULTIES:
            for reg in REGISTERS:
                total_seeds += len(entry["difficulty_levels"].get(diff, {}).get(reg, []))
        if entry["crisis_adjacent"]:
            crisis_count += 1

    print(f"\n=== Taxonomy complete ===")
    print(f"  Intents: {len(taxonomy)} ({crisis_count} crisis-adjacent)")
    print(f"  Difficulties: {len(DIFFICULTIES)} ({', '.join(DIFFICULTIES)})")
    print(f"  Registers: {len(REGISTERS)} ({', '.join(REGISTERS)})")
    print(f"  Total seed phrasings: {total_seeds}")
    print(f"  Output: {OUT_PATH}")


if __name__ == "__main__":
    main()
