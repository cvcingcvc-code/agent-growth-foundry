"""Train a Qwen LoRA adapter on CUDA and save evidence for independent evaluation."""
from __future__ import annotations

import argparse
from collections import Counter
import gc
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import shutil
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from growthfoundry.config import get_config
from growthfoundry.dataset import read_approved

BASE_MODEL = 'Qwen/Qwen3-0.6B'
LEARNING_RATES = (5e-5, 1e-4, 2e-4, 5e-4)
SEED = 42
TRAINING_BUDGET_SECONDS = 2 * 60 * 60


def _ensure_hf_env(cfg) -> None:
    """On Windows, pre-set HF env vars to avoid symlink permission issues."""
    if platform.system() == 'Windows':
        if not os.getenv('HF_HUB_DISABLE_SYMLINKS'):
            print('[WARN] Windows: auto-setting HF_HUB_DISABLE_SYMLINKS=1 to avoid symlink errors.', flush=True)
            os.environ['HF_HUB_DISABLE_SYMLINKS'] = '1'
        os.environ.setdefault('HF_HUB_DISABLE_XET', '1')
    if cfg.hf_home:
        os.environ.setdefault('HF_HOME', cfg.hf_home)


def curriculum_stage(record: dict) -> int:
    if record.get('task_type') == 'code_gen':
        return 0
    if len(record['messages']) > 2 or record.get('task_type') in {'debug', 'multi_step'}:
        return 2
    return 1


def encode_records(records: list[dict], tokenizer, max_length: int) -> tuple[list[dict], Counter]:
    """Supervise each reply once, masking all input and earlier replies."""
    encoded = []
    counts = Counter({'answer_turns': 0, 'shortened_history_turns': 0, 'truncated_answer_turns': 0})
    for record in records:
        messages = record['messages']
        for end in range(1, len(messages), 2):
            reply = messages[end]['content'] + tokenizer.eos_token
            completion = tokenizer(reply, add_special_tokens=False)['input_ids']
            for start in range(0, end, 2):
                prompt = tokenizer.apply_chat_template(
                    messages[start:end], tokenize=False, add_generation_prompt=True, enable_thinking=False,
                )
                prefix = tokenizer(prompt, add_special_tokens=False)['input_ids']
                spare = max_length - len(prefix)
                if spare >= len(completion):
                    break
            if spare < 1:
                raise ValueError(f"{record['source_id']} turn {(end + 1) // 2}: prompt exceeds token budget")
            counts['answer_turns'] += 1
            counts['shortened_history_turns'] += int(start > 0)
            counts['truncated_answer_turns'] += int(len(completion) > spare)
            # A truncated answer must not get a synthetic end-of-sequence target.
            completion = completion[:spare]
            ids = prefix + completion
            encoded.append({'input_ids': ids, 'attention_mask': [1] * len(ids),
                            'labels': [-100] * len(prefix) + completion})
    return encoded, counts


def train_trial(settings, learning_rate, revision, trial_dir, tokenizer, train_data, eval_data) -> dict:
    import torch
    from peft import LoraConfig, TaskType, get_peft_model
    from torch.utils.data import SequentialSampler
    from transformers import (AutoModelForCausalLM, EarlyStoppingCallback, Trainer,
                              TrainerCallback, TrainingArguments, set_seed)

    started = time.monotonic()

    class TrainingDeadline(TrainerCallback):
        def check(self):
            if time.monotonic() - started >= TRAINING_BUDGET_SECONDS:
                raise SystemExit(f'BLOCKED: trial at learning rate {learning_rate:g} exceeded its two-hour budget.')

        def on_step_begin(self, args, state, control, **kwargs):
            self.check()

        def on_prediction_step(self, args, state, control, **kwargs):
            self.check()

    class CurriculumTrainer(Trainer):
        def _get_train_sampler(self, train_dataset=None):
            dataset = self.train_dataset if train_dataset is None else train_dataset
            return SequentialSampler(dataset)

    def collate(features):
        length = max(len(row['input_ids']) for row in features)
        padding = {'input_ids': tokenizer.pad_token_id, 'attention_mask': 0, 'labels': -100}
        return {
            key: torch.tensor([row[key] + [pad] * (length - len(row[key])) for row in features], dtype=torch.long)
            for key, pad in padding.items()
        }

    set_seed(SEED)
    native_bf16 = torch.cuda.get_device_capability()[0] >= 8 and torch.cuda.is_bf16_supported()
    dtype = torch.bfloat16 if native_bf16 else torch.float16
    base = AutoModelForCausalLM.from_pretrained(
        settings.model, revision=revision, torch_dtype=dtype, trust_remote_code=False,
    )
    base.config.use_cache = False
    resolved_revision = base.config._commit_hash or revision
    lora = LoraConfig(r=settings.rank, lora_alpha=settings.alpha, lora_dropout=0.05,
                      bias='none', task_type=TaskType.CAUSAL_LM,
                      target_modules=['q_proj', 'k_proj', 'v_proj', 'o_proj'])
    model = get_peft_model(base, lora)
    model.print_trainable_parameters()

    args = TrainingArguments(
        output_dir=str(trial_dir / 'checkpoints'), num_train_epochs=settings.epochs,
        learning_rate=learning_rate, seed=SEED, data_seed=SEED,
        per_device_train_batch_size=1, per_device_eval_batch_size=1,
        gradient_accumulation_steps=4, gradient_checkpointing=True,
        gradient_checkpointing_kwargs={'use_reentrant': False},
        fp16=dtype == torch.float16, bf16=dtype == torch.bfloat16,
        eval_strategy='epoch', save_strategy='epoch', save_total_limit=1,
        load_best_model_at_end=True, metric_for_best_model='eval_loss', greater_is_better=False,
        logging_steps=1, report_to='none', optim='adamw_torch', dataloader_pin_memory=False,
    )
    deadline = TrainingDeadline()
    callbacks = [deadline]
    if settings.early_stop:
        callbacks.append(EarlyStoppingCallback(early_stopping_patience=settings.patience))
    trainer_class = CurriculumTrainer if settings.curriculum else Trainer
    trainer = trainer_class(model=model, args=args, train_dataset=train_data, eval_dataset=eval_data,
                            data_collator=collate, processing_class=tokenizer, callbacks=callbacks)
    result = trainer.train()
    history = list(trainer.state.log_history)
    eval_loss = trainer.evaluate()['eval_loss']
    deadline.check()
    if not math.isfinite(eval_loss):
        raise SystemExit(f'BLOCKED: non-finite evaluation loss at learning rate {learning_rate:g}.')
    adapter = trial_dir / 'adapter'
    trainer.save_model(str(adapter))
    tokenizer.save_pretrained(str(adapter))
    return {'learning_rate': learning_rate, 'train_loss': result.training_loss, 'eval_loss': eval_loss,
            'epochs_completed': trainer.state.epoch, 'history': history,
            'elapsed_sec': round(time.monotonic() - started, 1), 'base_revision': resolved_revision,
            'dtype': str(dtype)}


def save_curves(trials: list[dict], path: Path) -> None:
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib import pyplot as plt

    fig, (train_axis, eval_axis) = plt.subplots(1, 2, figsize=(10, 4), layout='constrained')
    try:
        for trial in trials:
            for axis, metric in ((train_axis, 'loss'), (eval_axis, 'eval_loss')):
                points = [(row['epoch'], row[metric]) for row in trial['history'] if metric in row]
                if points:
                    epochs, losses = zip(*points)
                    axis.plot(epochs, losses, label=f"lr={trial['learning_rate']:g}",
                              marker='o' if metric == 'eval_loss' else None)
        for axis, title in ((train_axis, 'Training loss'), (eval_axis, 'Validation loss')):
            axis.set(title=title, xlabel='Epoch', ylabel='Loss')
            if axis.lines:
                axis.legend()
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, dpi=150)
    finally:
        plt.close(fig)


def parse_settings() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument('--dataset', default='data/seed/sft_examples.jsonl')
    parser.add_argument('--model', default=BASE_MODEL)
    parser.add_argument('--output', default='models/qwen3-0.6b-lora-v0')
    parser.add_argument('--epochs', type=float, help='default: 1, or 6 with --early-stop')
    parser.add_argument('--learning-rate', type=float, default=2e-4, help='used without --lr-search')
    parser.add_argument('--lr-search', action='store_true', help='train four fresh adapters and select by eval loss')
    parser.add_argument('--rank', type=int, choices=(4, 8, 16, 32), default=8)
    parser.add_argument('--alpha', type=int, help='LoRA alpha (default: twice rank)')
    parser.add_argument('--max-length', type=int, default=512)
    parser.add_argument('--early-stop', action='store_true')
    parser.add_argument('--patience', type=int, default=3, help='epochs without eval loss improvement')
    parser.add_argument('--curriculum', action='store_true', help='order each epoch from simpler to harder tasks')
    parser.add_argument('--dry-run', action='store_true')
    settings = parser.parse_args()
    if settings.epochs is None:
        settings.epochs = 6 if settings.early_stop else 1
    if settings.alpha is None:
        settings.alpha = settings.rank * 2
    if not 128 <= settings.max_length <= 8192:
        parser.error('max-length out of allowed range')
    if not math.isfinite(settings.epochs) or settings.epochs <= 0:
        parser.error('epochs must be finite and positive')
    if not math.isfinite(settings.learning_rate) or settings.learning_rate <= 0:
        parser.error('learning-rate must be finite and positive')
    if settings.alpha <= 0 or settings.patience <= 0:
        parser.error('alpha and patience must be positive')
    return settings


def main() -> None:
    settings = parse_settings()
    _ensure_hf_env(get_config())
    splits = read_approved(settings.dataset)
    dataset_hash = hashlib.sha256(Path(settings.dataset).read_bytes()).hexdigest()
    learning_rates = LEARNING_RATES if settings.lr_search else (settings.learning_rate,)
    settings_report = {
        'dataset': settings.dataset, 'dataset_sha256': dataset_hash,
        'train': len(splits['train']), 'eval': len(splits['eval']), 'seed': SEED,
        'train_answer_turns': sum(len(row['messages']) // 2 for row in splits['train']),
        'rank': settings.rank, 'alpha': settings.alpha, 'max_length': settings.max_length,
        'epochs': settings.epochs, 'early_stop': settings.early_stop, 'patience': settings.patience,
        'curriculum': settings.curriculum, 'learning_rates': learning_rates,
    }
    if settings.dry_run:
        print(json.dumps({'status': 'CONFIG_VALIDATED_ONLY_NOT_TRAINED', 'base': settings.model,
                          'output': settings.output, **settings_report}, ensure_ascii=False, indent=2))
        return

    try:
        import torch
    except ImportError as ex:
        raise SystemExit(f'Missing package {ex}; install pip install -e ".[train]"') from ex
    if not torch.cuda.is_available():
        raise SystemExit('BLOCKED: CUDA GPU not found. No genuine Qwen LoRA training occurred.')
    try:
        import matplotlib
        import peft
        from transformers import AutoTokenizer
    except ImportError as ex:
        raise SystemExit(f'Missing package {ex}; install pip install -e ".[train]"') from ex

    tokenizer = AutoTokenizer.from_pretrained(settings.model, trust_remote_code=False)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    train_records = splits['train']
    if settings.curriculum:
        train_records = sorted(train_records, key=curriculum_stage)
    train_data, train_counts = encode_records(train_records, tokenizer, settings.max_length)
    eval_data, eval_counts = encode_records(splits['eval'], tokenizer, settings.max_length)
    out = Path(settings.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    curve_path = Path('outputs') / f'{out.resolve().name}-training-curves.png'
    trials = []
    best = None
    revision = tokenizer.init_kwargs.get('_commit_hash')

    with tempfile.TemporaryDirectory(prefix='.lora-', dir=out.parent) as staging:
        stage = Path(staging)
        winner = stage / 'winner'
        for rate in learning_rates:
            with tempfile.TemporaryDirectory(prefix='trial-', dir=stage) as trial_path:
                trial_dir = Path(trial_path)
                trial = train_trial(settings, rate, revision, trial_dir, tokenizer, train_data, eval_data)
                revision = trial['base_revision']
                trials.append(trial)
                if best is None or trial['eval_loss'] < best['eval_loss']:
                    best = trial
                    if winner.exists():
                        shutil.rmtree(winner)
                    (trial_dir / 'adapter').rename(winner)
            gc.collect()
            torch.cuda.empty_cache()

        save_curves(trials, stage / 'training-curves.png')
        report = {
            **settings_report,
            'status': 'TRAINING_FINISHED_NEEDS_INDEPENDENT_EVALUATION', 'base_model': settings.model,
            'base_revision': revision, 'base_license': 'Apache-2.0' if settings.model == BASE_MODEL else None,
            'gpu': torch.cuda.get_device_name(0), 'dtype': best['dtype'],
            'train_size': len(train_records), 'eval_size': len(splits['eval']),
            'train_encoding': train_counts, 'eval_encoding': eval_counts,
            'learning_rate': best['learning_rate'], 'epochs_completed': best['epochs_completed'],
            'train_loss': best['train_loss'], 'eval_loss': best['eval_loss'],
            'training_curves': str(curve_path), 'trials': trials,
            'limitation': 'Compare against the current champion on the fixed eval set before promotion.',
        }
        report_name = 'training_report.json'
        (winner / report_name).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        curve_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(stage / 'training-curves.png', curve_path)
        if out.exists():
            for artifact in winner.iterdir():
                if artifact.name != report_name:
                    artifact.replace(out / artifact.name)
            (winner / report_name).replace(out / report_name)
        else:
            winner.rename(out)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
