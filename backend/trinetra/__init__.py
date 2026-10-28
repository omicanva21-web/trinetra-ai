"""Trinetra AI backend."""
import os

os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")  # hide OpenCV's per-retry camera warnings; we report problems ourselves
os.environ.setdefault("OPENCV_VIDEOIO_PRIORITY_OBSENSOR", "0")  # skip the Orbbec depth-camera probe (noisy, not used)
