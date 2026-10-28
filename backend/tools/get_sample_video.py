"""Download OpenCV's public pedestrian sample video (clips/vtest.avi, 8 MB) for the 'real sample clip' camera."""
import sys
import urllib.request
from pathlib import Path

URL = "https://raw.githubusercontent.com/opencv/opencv/master/samples/data/vtest.avi"
dest = Path(__file__).resolve().parents[2] / "clips" / "vtest.avi"

if dest.exists() and dest.stat().st_size > 1_000_000:
    print(f"sample video already present: {dest}")
    sys.exit(0)
dest.parent.mkdir(parents=True, exist_ok=True)
print("downloading the sample pedestrian video (8 MB)...")
try:
    tmp = dest.with_suffix(".part")
    urllib.request.urlretrieve(URL, tmp)
    tmp.replace(dest)
    print(f"saved {dest}")
except Exception as exc:  # offline: the camera tile will say the file is missing; everything else still works
    print(f"could not download the sample video ({exc}). The 'real sample clip' camera will show 'No video'.")
