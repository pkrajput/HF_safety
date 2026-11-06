#!/usr/bin/env python3
"""Optional Transformers reporting-boundary capture; run while weights/GPUs are available.

This records token IDs, full-vocabulary next-token entropy and selected hidden states.
It does NOT identify a causal mechanism. Compare rendering with vLLM before interpretation.
Native Mistral chat rendering is not silently substituted with a Transformers rendering.
"""
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--index', required=True)
parser.add_argument('--model', required=True)
parser.add_argument('--model-root', required=True)
parser.add_argument('--out', required=True)
parser.add_argument('--limit', type=int, default=24)
parser.add_argument('--layers', default='-1,-2,-4')
parser.add_argument('--positions', type=int, default=8)
args = parser.parse_args()
entries = [e for e in json.loads(Path(args.index).read_text()) if e['model']['id'] == args.model][:args.limit]
if not entries:
    raise SystemExit('No matching replay contexts')
config = entries[0]['model']
if config['family'] == 'mistral' and '--tokenizer-mode' in config.get('serve_extra', []):
    raise SystemExit('Native Mistral template requires a separately validated replay adapter. '
                     'Retain the raw requests; use Qwen/Apertus for this capture.')
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

snapshot = Path(args.model_root)/args.model/config['revision']
tokenizer = AutoTokenizer.from_pretrained(snapshot, local_files_only=True)
model = AutoModelForCausalLM.from_pretrained(snapshot, torch_dtype=torch.bfloat16,
                                           device_map='auto', local_files_only=True)
model.eval()
layers = [int(x) for x in args.layers.split(',')]
out = Path(args.out)
out.mkdir(parents=True, exist_ok=True)
for entry in entries:
    if entry['model']['revision'] != config['revision']:
        raise ValueError('Mixed model revisions in replay input')
    request = entry['request']
    rendered = tokenizer.apply_chat_template(request['messages'], tokenize=False,
                  add_generation_prompt=True, **request.get('chat_template_kwargs', {}))
    tokens = tokenizer(rendered, return_tensors='pt', add_special_tokens=False)
    device = model.get_input_embeddings().weight.device
    tokens = {k: v.to(device) for k, v in tokens.items()}
    with torch.inference_mode():
        output = model(**tokens, output_hidden_states=True, use_cache=False)
        logits = output.logits[0, -1].float()
        log_probs = torch.log_softmax(logits, dim=-1)
        entropy = -(log_probs.exp()*log_probs).sum().item()
        hidden = {str(layer): output.hidden_states[layer][0, -args.positions:].cpu()
                  for layer in layers}
    torch.save({'input_ids': tokens['input_ids'].cpu(), 'hidden_states': hidden,
                'last_token_logits': logits.cpu(), 'entropy_nats': entropy,
                'entry': entry, 'rendered_prompt': rendered,
                'capture_note': 'Transformers replay; validate template and logit agreement with serving engine.'},
               out/(entry['id']+'.pt'))
    print(entry['id'], tokens['input_ids'].shape[-1], entropy, flush=True)
