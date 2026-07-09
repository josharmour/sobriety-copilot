#!/usr/bin/env python3
"""Quick generation smoke test: load a merged model, generate answers for a
couple recovery questions with a gold passage in context (mirrors the
training/inference format). Used to detect DPO over-optimization degradation
before committing to a full eval."""
from __future__ import annotations

import sys

from unsloth import FastLanguageModel
import torch

MODEL = sys.argv[1]

SYSTEM = (
    "You are a knowledgeable, direct guide to recovery literature. Lead with "
    "the answer, ground it in the provided passages, name the work by title, "
    "and never claim personal recovery experience."
)
CASES = [
    ("What does the Big Book say about resentment?",
     'From "Alcoholics Anonymous": Resentment is the number one offender. It '
     "destroys more alcoholics than anything else. From it stem all forms of "
     "spiritual disease, for we have been not only mentally and physically ill, "
     "we have been spiritually sick."),
    ("I keep relapsing and feel hopeless. What can I do?",
     'From "Living Sober": Staying sober one day at a time works when the whole '
     "lifetime seems too much. We don't drink today, and we go to meetings, and "
     "we call another alcoholic when the urge is strong."),
]

model, tok = FastLanguageModel.from_pretrained(
    MODEL, max_seq_length=4096, dtype=torch.bfloat16, load_in_4bit=False)
FastLanguageModel.for_inference(model)

for q, ctx in CASES:
    msgs = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"Relevant passages:\n{ctx}\n\nQuestion: {q}"},
    ]
    prompt = tok.apply_chat_template(msgs, add_generation_prompt=True, tokenize=False)
    inputs = tok(text=prompt, return_tensors="pt").to(model.device)
    out = model.generate(**inputs, max_new_tokens=180, do_sample=False,
                         repetition_penalty=1.1, pad_token_id=tok.eos_token_id)
    text = tok.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
    print(f"\n=== Q: {q}\n{text.strip()}\n")
