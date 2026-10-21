"""Real CPU weight updates on a tiny classification task; NOT an LLM.

This confirms the local-training plumbing: train/evaluate/save/reload.
Synthetic examples are illustrative, not production-grade evaluation.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import time

import torch
from torch import nn

CLASSES = ["GUIDE", "TOOL", "REJECT"]
BUCKETS = 8192


def featurize(text: str, max_tokens: int = 48):
    text = text.strip()
    chars = [text[i:i+2] for i in range(max(1, len(text)-1))]
    if not chars:
        chars = [text]
    return [1 + int.from_bytes(hashlib.blake2b(x.encode('utf-8'), digest_size=4).digest(), 'big') % (BUCKETS-1) for x in chars[:max_tokens]]


class TinyClassifier(nn.Module):
    def __init__(self):
        super().__init__()
        self.embedding = nn.Embedding(BUCKETS, 32, padding_idx=0)
        self.linear = nn.Linear(32, len(CLASSES))

    def forward(self, ids):
        mask = (ids != 0).unsqueeze(-1)
        em = self.embedding(ids)
        pooled = (em * mask).sum(1) / mask.sum(1).clamp(min=1)
        return self.linear(pooled)


def batch_encode(texts):
    features = [featurize(s) for s in texts]
    width = max(len(x) for x in features)
    return torch.tensor([s + [0]*(width-len(s)) for s in features], dtype=torch.long)


def evaluate(model, records):
    model.eval()
    with torch.no_grad():
        x = batch_encode([r['text'] for r in records])
        y = torch.tensor([CLASSES.index(r['label']) for r in records])
        logits = model(x)
        correct = int((logits.argmax(-1) == y).sum())
        loss = float(nn.functional.cross_entropy(logits, y).item())
    return {"total": len(records), "correct": correct, "accuracy": round(correct / len(records), 4), "loss": round(loss, 5)}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--dataset', default='data/seed/classifier_examples.jsonl')
    p.add_argument('--epochs', type=int, default=8)
    p.add_argument('--out', default='models/smoke')
    p.add_argument('--report', default='data/reports/smoke_train.json')
    args = p.parse_args()
    if not 1 <= args.epochs <= 300:
        p.error('epochs must be between 1 and 300')
    records = [json.loads(line) for line in Path(args.dataset).read_text(encoding='utf-8').splitlines() if line.strip()]
    assert all(r.get('rights') == 'self_authored' and r.get('approved') is True and r.get('label') in CLASSES for r in records)
    train = [r for r in records if r['split'] == 'train']
    evals = [r for r in records if r['split'] == 'eval']
    assert len(train) >= 9 and len(evals) >= 3
    torch.set_num_threads(min(2, torch.get_num_threads()))
    torch.manual_seed(20261021)
    model = TinyClassifier()
    before = evaluate(model, evals)
    x = batch_encode([r['text'] for r in train]); y = torch.tensor([CLASSES.index(r['label']) for r in train])
    optim = torch.optim.AdamW(model.parameters(), lr=0.035)
    start = time.perf_counter()
    first_weight = model.linear.weight.detach().clone()
    for epoch in range(args.epochs):
        model.train()
        optim.zero_grad()
        loss = nn.functional.cross_entropy(model(x), y)
        loss.backward()
        optim.step()
    updated = bool(not torch.allclose(first_weight, model.linear.weight))
    after = evaluate(model, evals)
    dest = Path(args.out)
    dest.mkdir(parents=True, exist_ok=True)
    weights_path = dest / 'classifier.pt'
    torch.save({'state_dict': model.state_dict(), 'classes': CLASSES, 'num_buckets': BUCKETS, 'seed': 20261021}, weights_path)
    clone = TinyClassifier()
    clone.load_state_dict(torch.load(weights_path, map_location='cpu', weights_only=True)['state_dict'])
    clone_eval = evaluate(clone, evals)
    assert clone_eval == after, 'checkpoint failed reload consistency check'
    assert updated, 'model weights did not change'
    report = {
        'model_type': 'TINY_HASHED_BIGRAM_CLASSIFIER_NOT_LLM',
        'status': 'SMOKE_PASS', 'source': 'self-authored, synthetic examples',
        'train_count': len(train), 'eval_count': len(evals), 'epochs': args.epochs,
        'baseline': before, 'after': after,
        'checkpoint_reload_pass': True, 'weights_changed': updated,
        'checkpoint_sha256': hashlib.sha256(weights_path.read_bytes()).hexdigest(),
        'elapsed_sec': round(time.perf_counter()-start, 3),
        'caveat': 'Tiny synthetic eval; no evidence of commercial quality or generalization.'
    }
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
