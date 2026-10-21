"""Load locally produced LoRA weights; local offline inference after first HF cache download."""
import argparse
p=argparse.ArgumentParser()
p.add_argument('--model',default='Qwen/Qwen3-0.6B')
p.add_argument('--adapter',required=True)
p.add_argument('--question',required=True)
p.add_argument('--max-new-tokens',type=int,default=128)
a=p.parse_args()
try:
    import torch
    from transformers import AutoTokenizer, AutoModelForCausalLM
    from peft import PeftModel
except ImportError as ex: raise SystemExit(f'Missing deps: {ex}')
if not torch.cuda.is_available():
    raise SystemExit('CUDA GPU missing; adapter inference is configured for GPU only in V1.')
tokenizer=AutoTokenizer.from_pretrained(a.adapter)
base=AutoModelForCausalLM.from_pretrained(a.model,torch_dtype=torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16,trust_remote_code=False).to('cuda')
model=PeftModel.from_pretrained(base,a.adapter).eval()
text=tokenizer.apply_chat_template([{'role':'user','content':a.question}],tokenize=False,add_generation_prompt=True,enable_thinking=False)
inputs=tokenizer(text,return_tensors='pt',add_special_tokens=False).to('cuda')
with torch.inference_mode():
    generated=model.generate(**inputs,max_new_tokens=a.max_new_tokens,do_sample=False,pad_token_id=tokenizer.eos_token_id)
print(tokenizer.decode(generated[0][inputs['input_ids'].shape[1]:],skip_special_tokens=True))
