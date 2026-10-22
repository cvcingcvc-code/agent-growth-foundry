"""Local model CLI: chat with the base model or a trained LoRA adapter.

Safety and usability:
- enable_thinking=False on the chat template (Qwen3 non-thinking mode)
- max-new-tokens limit and a per-turn timeout guard that REALLY stops the
  generation (round-4.1 fix): a TimeoutStoppingCriteria is registered with
  model.generate(), so the generation loop checks the deadline between
  steps and returns early - the old daemon-thread guard left the model
  generating in the background after the timeout fired.
- LoRA adapters are only loaded when adapter_config.json records the SAME
  base model (round-4.1 fix): a 0.6B adapter must never be mounted onto an
  incompatible base; cross-base mounting exits with a clear error.
- clear errors when CUDA/adapter/packages are missing
- --version-info shows model/adapter versions without loading weights
- --adapter none uses the raw base model; same sampling config (greedy) for
  base-vs-adapter comparison under identical conditions

Usage:
  python scripts/chat_local.py --adapter models/qwen3-0.6b-lora-v0 --question "你的问题"
  python scripts/chat_local.py --adapter none --question "写一个 Python 函数判断质数"
  python scripts/chat_local.py --adapter models/qwen3-0.6b-lora-v0          # interactive REPL
  python scripts/chat_local.py --version-info --adapter models/qwen3-0.6b-lora-v0
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description='Local model chat CLI (base or LoRA adapter)')
    p.add_argument('--model', default='Qwen/Qwen3-0.6B', help='base model id')
    p.add_argument('--adapter', default='models/qwen3-0.6b-lora-v0',
                   help='LoRA adapter dir, or "none" for the raw base model')
    p.add_argument('--question', default=None, help='one-shot question; omit for interactive mode')
    p.add_argument('--max-new-tokens', type=int, default=256)
    p.add_argument('--timeout-sec', type=int, default=180, help='per-turn generation timeout')
    p.add_argument('--version-info', action='store_true', help='print model/adapter metadata and exit')
    return p


def adapter_version_info(adapter: str | None, base: str) -> dict:
    """Pure metadata inspection, no weights loaded."""
    info = {'base_model': base, 'adapter': adapter or 'none', 'mode': 'base' if adapter in (None, 'none') else 'lora'}
    if adapter and adapter != 'none':
        cfg = Path(adapter) / 'adapter_config.json'
        if not cfg.exists():
            raise FileNotFoundError(f'adapter config missing: {cfg}')
        data = json.loads(cfg.read_text(encoding='utf-8'))
        info['lora'] = {'r': data.get('r'), 'lora_alpha': data.get('lora_alpha'),
                        'target_modules': data.get('target_modules')}
        weights = Path(adapter) / 'adapter_model.safetensors'
        info['adapter_weights_bytes'] = weights.stat().st_size if weights.exists() else 0
    return info


def adapter_base_matches(adapter: str, target_base: str) -> tuple[bool, str, str]:
    """Read adapter_config.json and compare its recorded base against the
    model actually being loaded (round-4.1 Task 3).

    Returns (compatible, adapter_base, reason). Unknown provenance is
    incompatible by default (conservative).
    """
    cfg = Path(adapter) / 'adapter_config.json'
    data = json.loads(cfg.read_text(encoding='utf-8'))
    adapter_base = (data.get('base_model') or data.get('base_model_name_or_path')
                    or data.get('_name_or_path') or '')
    if not adapter_base:
        return False, '', 'adapter config records no base model; refusing to mount'
    norm = lambda s: str(s).replace('\\', '/').rstrip('/')
    if norm(adapter_base) != norm(target_base):
        return (False, adapter_base,
                f'adapter was trained on {adapter_base!r}, refusing to mount onto {target_base!r}; '
                f'switching base = new model series (retrain + re-accept)')
    return True, adapter_base, 'base match'


def load_model_and_tokenizer(model_id: str, adapter: str | None):
    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError as ex:
        raise SystemExit(f'缺少依赖包: {ex}；请安装 pip install -e ".[train]"')
    if not torch.cuda.is_available():
        raise SystemExit('BLOCKED: 未检测到 CUDA GPU；本地推理配置为 GPU-only（V1）。')
    if adapter and adapter != 'none':
        if not (Path(adapter) / 'adapter_config.json').exists():
            raise SystemExit(f'adapter 不存在或不完整: {adapter}')
        ok, _ab, reason = adapter_base_matches(adapter, model_id)
        if not ok:
            raise SystemExit(f'BLOCKED: LoRA 基座不兼容 — {reason}')
    tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=False)
    dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    base = AutoModelForCausalLM.from_pretrained(model_id, torch_dtype=dtype,
                                                trust_remote_code=False).to('cuda')
    model = base
    if adapter and adapter != 'none':
        from peft import PeftModel
        model = PeftModel.from_pretrained(base, adapter)
    model.eval()
    return model, tokenizer


def generate_once(model, tokenizer, question: str, max_new_tokens: int, timeout_sec: int) -> dict:
    """Single greedy generation with a REAL timeout guard (round-4.1 fix).

    The deadline is enforced inside the generation loop via a
    StoppingCriteria, so a timed-out turn actually stops generating instead
    of leaving the model running in a daemon thread.
    """
    import threading
    import torch

    result: dict = {'text': '', 'error': None, 'elapsed_sec': 0.0, 'new_tokens': 0,
                    'timed_out': False}

    class DeadlineStoppingCriteria:
        """Cooperative stop: generate() polls this between decode steps."""
        def __init__(self, deadline: float):
            self.deadline = deadline

        def __call__(self, input_ids, scores, **kwargs) -> 'torch.BoolTensor':
            import torch as _t
            return _t.tensor([time.monotonic() >= self.deadline], dtype=_t.bool,
                             device=input_ids.device)

    def run(stop_criteria):
        t0 = time.monotonic()
        try:
            text = tokenizer.apply_chat_template(
                [{'role': 'user', 'content': question}], tokenize=False,
                add_generation_prompt=True, enable_thinking=False)
            inputs = tokenizer(text, return_tensors='pt', add_special_tokens=False).to('cuda')
            gen_kwargs = dict(**inputs, max_new_tokens=max_new_tokens, do_sample=False,
                              pad_token_id=tokenizer.eos_token_id)
            if stop_criteria is not None:
                gen_kwargs['stopping_criteria'] = stop_criteria
            with torch.inference_mode():
                out = model.generate(**gen_kwargs)
            new_tokens = out.shape[1] - inputs['input_ids'].shape[1]
            result['text'] = tokenizer.decode(out[0][inputs['input_ids'].shape[1]:], skip_special_tokens=True)
            result['new_tokens'] = int(new_tokens)
            result['elapsed_sec'] = round(time.monotonic() - t0, 1)
        except Exception as ex:  # surface generation errors instead of crashing the REPL
            result['error'] = f'{type(ex).__name__}: {ex}'

    deadline = time.monotonic() + timeout_sec
    stop_criteria = None
    try:
        from transformers import StoppingCriteriaList
        # transformers>=4.40 polls kwargs-based criteria each decode step, so
        # the deadline check inside the generation loop actually stops it.
        stop_criteria = StoppingCriteriaList([DeadlineStoppingCriteria(deadline)])
    except ImportError:
        stop_criteria = None  # very old transformers: watcher thread reports honestly below

    thread = threading.Thread(target=run, args=(stop_criteria,), daemon=True)
    thread.start()
    thread.join(timeout=timeout_sec + 15)  # grace for the criteria to fire + finalize
    if thread.is_alive():
        # Criteria failed to stop the run (very old transformers): report
        # honestly instead of pretending the generation was stopped.
        result['error'] = (f'生成超时（>{timeout_sec}s）；stopping-criteria 未能在宽限期内结束生成，'
                           f'推理可能仍在后台进行，请检查 GPU 占用。')
        result['timed_out'] = True
    elif result['error'] is None and result['elapsed_sec'] >= timeout_sec:
        # The stopping-criteria fired mid-generation: partial text may be
        # present; mark it honestly so callers know this answer is truncated.
        result['error'] = (f'生成超时（>={timeout_sec}s），已通过 stopping-criteria 中止本轮；'
                           f'以下为截断的部分回答。')
        result['timed_out'] = True
    return result


def print_turn(label: str, res: dict) -> None:
    if res['error']:
        print(f'[错误] {res["error"]}')
        return
    print(f'--- {label}（{res["new_tokens"]} tokens, {res["elapsed_sec"]}s）---')
    print(res['text'].strip() or '（空回答）')


def run_interactive(model, tokenizer, max_new_tokens: int, timeout_sec: int) -> None:
    print('交互模式（输入 quit/exit 退出；输入空行忽略）：')
    while True:
        try:
            question = input('你> ').strip()
        except (EOFError, KeyboardInterrupt):
            print('\n退出。')
            return
        if question.lower() in {'quit', 'exit'}:
            print('退出。')
            return
        if not question:
            continue
        res = generate_once(model, tokenizer, question, max_new_tokens, timeout_sec)
        print_turn('模型', res)


def main() -> None:
    a = build_arg_parser().parse_args()
    if a.version_info:
        print(json.dumps(adapter_version_info(a.adapter, a.model), ensure_ascii=False, indent=2))
        return
    model, tokenizer = load_model_and_tokenizer(a.model, a.adapter)
    label = f'adapter={a.adapter}' if a.adapter != 'none' else 'base model（原始基座）'
    print(f'[已加载] {label}；非思考模式；greedy 采样；max_new_tokens={a.max_new_tokens}；超时={a.timeout_sec}s')
    if a.question:
        res = generate_once(model, tokenizer, a.question, a.max_new_tokens, a.timeout_sec)
        print_turn('回答', res)
        if res['error']:
            sys.exit(1)
    else:
        run_interactive(model, tokenizer, a.max_new_tokens, a.timeout_sec)


if __name__ == '__main__':
    main()
