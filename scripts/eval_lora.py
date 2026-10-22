"""Evaluate base model vs LoRA adapter on the eval split (independent-evaluation evidence).

Small-sample comparison only: 4 eval records, NOT proof of improvement.
Base model can run on CPU or GPU; adapter inference prefers GPU when available.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from growthfoundry.dataset import read_approved


def build_comparison_report(records, base_answers, adapter_answers, adapter_dir, device_note,
                            dataset_sha256: str | None = None):
    """Assemble the base-vs-LoRA comparison structure (pure, testable)."""
    import hashlib
    assert len(records) == len(base_answers) == len(adapter_answers), 'length mismatch'
    items = []
    for rec, base_out, lora_out in zip(records, base_answers, adapter_answers):
        items.append({
            'source_id': rec['source_id'],
            'question': rec['messages'][0]['content'],
            'reference_answer': rec['messages'][1]['content'],
            'base_answer': base_out,
            'lora_answer': lora_out,
        })
    report = {
        'status': 'BASE_VS_LORA_COMPARISON_ONLY_NOT_SIGNIFICANCE_CLAIM',
        'adapter': str(adapter_dir),
        'device_note': device_note,
        'samples': len(items),
        'items': items,
        'limitation': 'Only 4 eval seed samples; no statistically significant improvement can be claimed. Human-labeled holdout required before promotion.',
    }
    if dataset_sha256:
        report['dataset_fingerprint'] = {'sha256': dataset_sha256, 'count': len(records)}
    return report


def dataset_sha256_of(path) -> str:
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--dataset', default='data/seed/sft_examples.jsonl')
    p.add_argument('--model', default='Qwen/Qwen3-0.6B')
    p.add_argument('--adapter', default='models/qwen3-0.6b-lora-v0')
    p.add_argument('--output', default='outputs/base_vs_lora_eval.json')
    p.add_argument('--max-new-tokens', type=int, default=96)
    a = p.parse_args()

    import torch
    from transformers import AutoTokenizer, AutoModelForCausalLM
    from peft import PeftModel

    splits = read_approved(a.dataset)
    eval_records = splits['eval']
    questions = [r['messages'][0]['content'] for r in eval_records]

    dtype = torch.bfloat16 if (torch.cuda.is_available() and torch.cuda.is_bf16_supported()) else torch.float32
    if torch.cuda.is_available():
        device, device_note = 'cuda', 'GPU: ' + torch.cuda.get_device_name(0)
    else:
        device, device_note = 'cpu', 'CPU fallback (no CUDA); adapter inference unsupported in V1 but base comparison still valid'

    tokenizer = AutoTokenizer.from_pretrained(a.model, trust_remote_code=False)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    base = AutoModelForCausalLM.from_pretrained(a.model, dtype=dtype, trust_remote_code=False).to(device).eval()

    def answer(model, question):
        text = tokenizer.apply_chat_template([{'role': 'user', 'content': question}], tokenize=False, add_generation_prompt=True, enable_thinking=False)
        inputs = tokenizer(text, return_tensors='pt', add_special_tokens=False).to(device)
        with torch.inference_mode():
            out = model.generate(**inputs, max_new_tokens=a.max_new_tokens, do_sample=False, pad_token_id=tokenizer.eos_token_id)
        return tokenizer.decode(out[0][inputs['input_ids'].shape[1]:], skip_special_tokens=True).strip()

    base_answers = [answer(base, q) for q in questions]

    adapter_answers = None
    if device == 'cuda':
        lora = PeftModel.from_pretrained(base, a.adapter).eval()
        adapter_answers = [answer(lora, q) for q in questions]
        device_note += '; LoRA answered on GPU'
    else:
        adapter_answers = ['SKIPPED: CUDA unavailable, adapter inference is GPU-only in V1'] * len(questions)
        device_note += '; LoRA answers skipped'

    report = build_comparison_report(eval_records, base_answers, adapter_answers,
                                     a.adapter, device_note, dataset_sha256_of(a.dataset))
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('status', 'adapter', 'device_note', 'samples')}, ensure_ascii=False, indent=2))
    print('saved to', out)


if __name__ == '__main__':
    main()
