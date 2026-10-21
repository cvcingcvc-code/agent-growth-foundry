"""Load the trained local tiny model and classify an example."""
import argparse
import json
from pathlib import Path
import torch
from train_smoke import TinyClassifier, batch_encode, CLASSES

p = argparse.ArgumentParser()
p.add_argument('--checkpoint', default='models/smoke/classifier.pt')
p.add_argument('--text', default='这是一套原创的 AI 工具部署教程和操作说明')
a = p.parse_args()
model = TinyClassifier()
model.load_state_dict(torch.load(Path(a.checkpoint), map_location='cpu', weights_only=True)['state_dict'])
model.eval()
with torch.no_grad():
    probs = torch.softmax(model(batch_encode([a.text])), -1)[0].tolist()
print(json.dumps({'text':a.text, 'label': CLASSES[probs.index(max(probs))], 'probabilities':dict(zip(CLASSES, [round(v,4) for v in probs])), 'caveat':'Toy model; never use its predictions to authorize distribution or training.'}, ensure_ascii=False, indent=2))
