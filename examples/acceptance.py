"""Small real CUDA pipeline for user-triggered integration acceptance."""
import argparse
import json
import math
from pathlib import Path
import torch

parser=argparse.ArgumentParser()
parser.add_argument('mode',choices=['train','evaluate','infer'])
parser.add_argument('--output-dir',required=True)
args=parser.parse_args()
if not torch.cuda.is_available():
    raise RuntimeError('CUDA is required; CPU fallback is disabled')
torch.manual_seed(42)
root=Path(args.output_dir);root.mkdir(parents=True,exist_ok=True)
device=torch.device('cuda:0')
model=torch.nn.Linear(8,2).to(device)
x=torch.arange(512,dtype=torch.float32,device=device).reshape(64,8)/512
y=torch.stack((x.mean(dim=1),x.sum(dim=1)/4),dim=1)
if args.mode=='train':
    optimizer=torch.optim.SGD(model.parameters(),lr=.1)
    for step in range(30):
        optimizer.zero_grad();loss=torch.nn.functional.mse_loss(model(x),y);loss.backward();optimizer.step()
        if step%10==0:print(json.dumps({'step':step,'loss':float(loss.detach()),'device':torch.cuda.get_device_name(0)}),flush=True)
    torch.save(model.state_dict(),root/'model.pt')
    print('Training complete; checkpoint saved.',flush=True)
else:
    model.load_state_dict(torch.load(root/'model.pt',map_location=device,weights_only=True));model.eval()
    with torch.no_grad():prediction=model(x)
    if args.mode=='evaluate':
        loss=float(torch.nn.functional.mse_loss(prediction,y))
        if not math.isfinite(loss):raise RuntimeError('Evaluation produced invalid metrics')
        (root/'metrics.json').write_text(json.dumps({'mse':loss,'device':torch.cuda.get_device_name(0),'samples':len(x)},indent=2))
        print('Evaluation passed; metrics saved.',flush=True)
    else:
        (root/'samples.json').write_text(json.dumps({'predictions':prediction[:5].cpu().tolist()},indent=2))
        print('Inference complete; samples saved.',flush=True)
