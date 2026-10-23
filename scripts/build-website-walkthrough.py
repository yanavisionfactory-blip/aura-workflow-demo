"""Render a captioned MP4 from captured, paused AURA walkthrough scenes.

Capture scene-NN.jpg from the public demo's ?scene=N view. The visible tour
caption is part of every capture. This script makes a still-frame walkthrough,
not a claim of live provider execution. ffmpeg must be installed.
"""
import argparse
import json
import subprocess
import tempfile
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('frames', type=Path)
parser.add_argument('--output', type=Path, default=Path('showcase/website-content/public/walkthrough.mp4'))
parser.add_argument('--ffmpeg', default='ffmpeg', help='Path to a verified ffmpeg executable')
args = parser.parse_args()
repo = Path(__file__).resolve().parents[1]
scenes = json.loads(subprocess.check_output(['node', '--input-type=module', '-e', "import {tour} from './src/showcase/website-content/scenario.mjs'; console.log(JSON.stringify(tour));"], cwd=repo, text=True))
args.output.parent.mkdir(parents=True, exist_ok=True)

def timestamp(seconds):
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    return f'{hours:02d}:{minutes:02d}:{seconds:02d}.000'

captions = ['WEBVTT', '']
start = 0
with tempfile.TemporaryDirectory(prefix='aura-film-', dir=args.frames) as temp:
    segments = []
    for index, scene in enumerate(scenes):
        frame = args.frames / f'scene-{index:02d}.jpg'
        if not frame.is_file() or frame.stat().st_size == 0:
            raise FileNotFoundError(frame)
        segment = Path(temp) / f'{index:02d}.mp4'
        subprocess.run([args.ffmpeg, '-hide_banner', '-loglevel', 'error', '-y', '-loop', '1', '-framerate', '10', '-i', str(frame), '-t', str(scene['seconds']), '-vf', 'scale=1280:880:force_original_aspect_ratio=decrease,pad=1280:880:(ow-iw)/2:(oh-ih)/2:color=0x080f18,setsar=1', '-c:v', 'libx264', '-preset', 'medium', '-tune', 'stillimage', '-crf', '25', '-pix_fmt', 'yuv420p', '-r', '10', '-g', '50', '-an', str(segment)], check=True)
        segments.append(segment)
        end = start + scene['seconds']
        captions.extend([f'{index+1}', f'{timestamp(start)} --> {timestamp(end)}', f'{scene["title"]}: {scene["caption"]}', ''])
        start = end
    listing = Path(temp) / 'segments.txt'
    listing.write_text(''.join(f"file '{segment}'\n" for segment in segments))
    subprocess.run([args.ffmpeg, '-hide_banner', '-loglevel', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', str(listing), '-c', 'copy', '-movflags', '+faststart', str(args.output)], check=True)
args.output.with_suffix('.vtt').write_text('\n'.join(captions))
print(json.dumps({'video':str(args.output.resolve()),'seconds':start,'scenes':len(scenes),'bytes':args.output.stat().st_size}))
