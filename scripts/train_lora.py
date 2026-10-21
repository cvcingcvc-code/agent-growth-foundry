"""Train an actual Qwen LoRA adapter locally on an NVIDIA GPU.

Never auto-download/train in CI, and never claim success if CUDA is unavailable.
The bundled 16/4 synthetic examples are strictly pipeline demos.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from growthfoundry.dataset import read_approved


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--dataset', default='data/seed/sft_examples.jsonl')
    p.add_argument('--model', default='Qwen/Qwen3-0.6B')
    p.add_argument('--output', default='models/qwen3-0.6b-lora-v0')
    p.add_argument('--epochs', type=float, default=1)
    p.add_argument('--learning-rate', type=float, default=2e-4,
                   help='optimizer learning rate; never claim a fixed optimal config without comparison')
    p.add_argument('--max-length', type=int, default=384)
    p.add_argument('--dry-run', action='store_true')
    a = p.parse_args()
    splits = read_approved(a.dataset)
    if a.max_length < 128 or a.max_length > 8192:
        p.error('max-length out of allowed range')
    if a.epochs <= 0:
        p.error('epochs must be positive')
    if a.dry_run:
        print(json.dumps({'status': 'CONFIG_VALIDATED_ONLY_NOT_TRAINED', 'base': a.model, 'train':len(splits['train']), 'eval':len(splits['eval']), 'output':a.output}, ensure_ascii=False, indent=2))
        return

    try:
        import torch
        from peft import LoraConfig, TaskType, get_peft_model
        from transformers import AutoTokenizer, AutoModelForCausalLM, Trainer, TrainingArguments
    except ImportError as ex:
        raise SystemExit(f'Missing package {ex}; install pip install -e ".[train]"')
    if not torch.cuda.is_available():
        raise SystemExit('BLOCKED: CUDA GPU not found. No genuine Qwen LoRA training occurred.')
    device_name = torch.cuda.get_device_name(0)
    dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    tokenizer = AutoTokenizer.from_pretrained(a.model, trust_remote_code=False)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    base = AutoModelForCausalLM.from_pretrained(a.model, torch_dtype=dtype, trust_remote_code=False)
    base.config.use_cache = False
    lora = LoraConfig(r=8, lora_alpha=16, lora_dropout=0.05, bias='none', task_type=TaskType.CAUSAL_LM,
                      target_modules=['q_proj','k_proj','v_proj','o_proj'])
    model = get_peft_model(base, lora)
    model.print_trainable_parameters()

    def encoded(item):
        msgs = item['messages']
        prefix_text = tokenizer.apply_chat_template([msgs[0]], tokenize=False, add_generation_prompt=True, enable_thinking=False)
        prefix = tokenizer(prefix_text, add_special_tokens=False)['input_ids']
        completion = tokenizer(msgs[1]['content'] + tokenizer.eos_token, add_special_tokens=False)['input_ids']
        spare = a.max_length - len(prefix)
        if spare < 8:
            raise ValueError('prompt too long; increase --max-length or shorten source sample')
        completion = completion[:spare]
        ids = prefix + completion
        return {'input_ids': ids, 'attention_mask': [1]*len(ids), 'labels': [-100]*len(prefix)+completion}

    from torch.utils.data import Dataset
    class RecordSet(Dataset):
        def __init__(self, records): self.items = [encoded(r) for r in records]
        def __len__(self): return len(self.items)
        def __getitem__(self, idx): return self.items[idx]

    def collate(features):
        length = max(len(i['input_ids']) for i in features)
        def pad(seq, value): return seq + [value] * (length-len(seq))
        return {k:torch.tensor([pad(f[k], val) for f in features],dtype=torch.long)
                for k,val in [('input_ids',tokenizer.pad_token_id),('attention_mask',0),('labels',-100)]}

    out = Path(a.output)
    train_dataset = RecordSet(splits['train'])
    eval_dataset = RecordSet(splits['eval'])
    args = TrainingArguments(
        output_dir=str(out), num_train_epochs=a.epochs, learning_rate=a.learning_rate,
        per_device_train_batch_size=1, per_device_eval_batch_size=1,
        gradient_accumulation_steps=4, gradient_checkpointing=True,
        gradient_checkpointing_kwargs={'use_reentrant':False},
        fp16=dtype == torch.float16, bf16=dtype == torch.bfloat16,
        eval_strategy='epoch', save_strategy='epoch', save_total_limit=2,
        load_best_model_at_end=True, metric_for_best_model='eval_loss', greater_is_better=False,
        logging_steps=1, report_to='none', optim='adamw_torch', dataloader_pin_memory=False,
    )
    trainer = Trainer(model=model,args=args,train_dataset=train_dataset,eval_dataset=eval_dataset,
                      data_collator=collate,processing_class=tokenizer)
    result = trainer.train()
    metrics = trainer.evaluate()
    trainer.save_model(str(out))
    tokenizer.save_pretrained(str(out))
    report = {
        'status':'TRAINING_FINISHED_NEEDS_INDEPENDENT_EVALUATION', 'base_model':a.model,
        'gpu':device_name,'dtype':str(dtype),'train_size':len(train_dataset),
        'eval_size':len(eval_dataset),'epochs':a.epochs,'learning_rate':a.learning_rate,
        'train_loss':result.training_loss,
        'eval_loss':metrics.get('eval_loss'),
        'limitation':'Small seed examples cannot demonstrate improved useful generation. Compare against current champion on fixed eval set before promotion.'
    }
    (out/'training_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__ == '__main__':
    main()
