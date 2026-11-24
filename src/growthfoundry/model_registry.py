"""Model registry: which base models exist, their capacity class, and which
adapters may be attached to which bases.

Rule (AGENTS.md): a PEFT LoRA adapter is dimension-bound to the base model it
was trained on. A 0.6B adapter MUST NOT be attached to a 4B/8B/30B base —
the weight shapes do not match and any apparent success is silently broken
output. The registry enforces this at lookup time, and `champion.py`
enforces the same rule again at promotion time (defense in depth).

Capacity and VRAM figures are DOCUMENTATION (rounded, from public quantization
indexes as of 2026-10), not measurements. Anything not measured on this
machine is labeled estimated.
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    family: str            # qwen3
    params_b: float        # total parameters (billions)
    active_params_b: float  # active parameters (MoE) or same as params
    vram_inference_gb: dict  # quant level -> estimated GB (documentation)
    vram_lora_train_gb: dict  # quant level -> estimated GB (documentation)
    notes: str = ''


REGISTRY: dict[str, ModelSpec] = {
    'Qwen/Qwen3-0.6B': ModelSpec(
        model_id='Qwen/Qwen3-0.6B', family='qwen3', params_b=0.6, active_params_b=0.6,
        vram_inference_gb={'fp16': 1.5, 'q8': 0.9, 'q4': 0.6},
        vram_lora_train_gb={'fp16': 4.0},
        notes='Current champion base. Trains on 6GB cards (measured on GTX 1660).'),
    'Qwen/Qwen3-1.7B': ModelSpec(
        model_id='Qwen/Qwen3-1.7B', family='qwen3', params_b=1.7, active_params_b=1.7,
        vram_inference_gb={'fp16': 4.0, 'q8': 2.2, 'q4': 1.4},
        vram_lora_train_gb={'fp16': 6.0},
        notes='Next size up; fp16 LoRA training needs ~6GB (estimated).'),
    'Qwen/Qwen3-4B': ModelSpec(
        model_id='Qwen/Qwen3-4B', family='qwen3', params_b=4.0, active_params_b=4.0,
        vram_inference_gb={'fp16': 8.0, 'q8': 4.0, 'q4': 2.0},
        vram_lora_train_gb={'fp16': 16.0, 'qlora': 8.0},
        notes='QLoRA training ~8-10GB (estimated); fp16 LoRA ~16GB (estimated).'),
    'Qwen/Qwen3-8B': ModelSpec(
        model_id='Qwen/Qwen3-8B', family='qwen3', params_b=8.0, active_params_b=8.0,
        vram_inference_gb={'fp16': 16.0, 'q8': 8.0, 'q4': 4.9},
        vram_lora_train_gb={'fp16': 24.0, 'qlora': 12.0},
        notes='QLoRA ~12GB / fp16 LoRA ~24GB (estimated); needs 12GB+ card.'),
    'Qwen/Qwen3-Coder-30B-A3B-Instruct': ModelSpec(
        model_id='Qwen/Qwen3-Coder-30B-A3B-Instruct', family='qwen3', params_b=30.0,
        active_params_b=3.3,
        vram_inference_gb={'fp16': 67.0, 'q8': 33.5, 'q5_k_m': 22.0, 'q4_k_m': 19.2},
        vram_lora_train_gb={'qlora': 17.5},
        notes='MoE coder; Q4_K_M inference ~19.7GB with 4K ctx (estimated); '
              'QLoRA training ~17.5GB per Unsloth docs (estimated).'),
}

# Known adapter -> base bindings measured on this machine.
ADAPTER_BINDINGS: dict[str, str] = {
    'models/qwen3-0.6b-lora-v0': 'Qwen/Qwen3-0.6B',
    'models/qwen3-0.6b-lora-v1': 'Qwen/Qwen3-0.6B',
    'models/qwen3-0.6b-lora-v2': 'Qwen/Qwen3-0.6B',
}


class ModelNotInRegistry(KeyError):
    pass


class AdapterBaseMismatch(ValueError):
    pass


def get_spec(model_id: str) -> ModelSpec:
    key = model_id if model_id in REGISTRY else f'Qwen/{model_id}'
    if key not in REGISTRY:
        raise ModelNotInRegistry(model_id)
    return REGISTRY[key]


def check_binding(adapter: str, base_model: str) -> None:
    """Raise AdapterBaseMismatch when the adapter is bound to another base."""
    bound = ADAPTER_BINDINGS.get(adapter)
    if bound is None:
        return  # unknown adapter: champion.py checks the config instead
    if bound.rstrip('/') != base_model:
        raise AdapterBaseMismatch(
            f'adapter {adapter} is bound to {bound}, not {base_model}; '
            f'a LoRA adapter is dimension-bound to its training base')


def resolve_adapter_base(adapter: str, requested_base: str) -> str:
    """Return the base the adapter must run on, or raise."""
    check_binding(adapter, requested_base)
    return requested_base


def upgrade_candidates(current_vram_gb: float) -> list[dict]:
    """Base models this machine could move to, given available VRAM (GB).
    Documentation only: training VRAM figures are estimated, not measured."""
    out = []
    for spec in REGISTRY.values():
        need = spec.vram_lora_train_gb.get('fp16') or spec.vram_lora_train_gb.get('qlora')
        fits_fp16 = spec.vram_lora_train_gb.get('fp16', 999) <= current_vram_gb
        fits_qlora = spec.vram_lora_train_gb.get('qlora', 999) <= current_vram_gb
        out.append({
            'model_id': spec.model_id,
            'params_b': spec.params_b,
            'fits_current_gpu_fp16': fits_fp16,
            'fits_current_gpu_qlora': fits_qlora,
            'estimated_train_vram_gb': need,
            'notes': spec.notes,
        })
    return out
