# Models

| File | What | Source | Licence |
| --- | --- | --- | --- |
| `nanodet_plus_m_416.onnx` | NanoDet-Plus-m 416, COCO, run by OpenCV DNN. Cameras set to **Fast** (default). | [OpenCV Zoo](https://github.com/opencv/opencv_zoo/tree/main/models/object_detection_nanodet) (`object_detection_nanodet_2022nov.onnx`), NanoDet by RangiLyu | Apache-2.0 (`LICENSE-NanoDet-Apache-2.0.txt`) |
| `yolox_s.onnx` | YOLOX-S, COCO, run by OpenCV DNN. Cameras set to **Accurate**. | [OpenCV Zoo](https://github.com/opencv/opencv_zoo/tree/main/models/object_detection_yolox) (`object_detection_yolox_2022nov.onnx`), YOLOX by Megvii | Apache-2.0 (`LICENSE-YOLOX-Apache-2.0.txt`) |
| `yolox_m.onnx` | YOLOX-M, COCO (Megvii release, BGR input). Cameras set to **Dense crowd**: run on 20 overlapping, enlarged tiles plus the whole frame, with ONNX Runtime when installed (else OpenCV DNN). | [YOLOX v0.1.1rc0 release](https://github.com/Megvii-BaseDetection/YOLOX/releases/tag/0.1.1rc0), SHA-256 `21ff6cfd…5b3f` | Apache-2.0 (`LICENSE-YOLOX-Apache-2.0.txt`) |
| `yolo26n.pt` | Ultralytics YOLO26 nano. Used for every camera once `install_yolo.bat` has installed Ultralytics. | [Ultralytics assets v8.4.0](https://github.com/ultralytics/assets/releases/tag/v8.4.0) | AGPL-3.0 (Ultralytics) |

If an ONNX file is missing it is downloaded on first use and checked against its SHA-256; Ultralytics downloads its own weights.

Measured on the bundled sample clip (2-core cloud machine, OpenCV 5): NanoDet 28 ms per frame, YOLOX-S 251 ms per frame;
both found the same three people on the frame compared; NanoDet produced one extra false box (a traffic cone).

Dense crowd mode, measured on a 62 s handheld phone video of a packed hall (854x480, people 15–60 px tall), 2-core
cloud CPU: NanoDet (Fast) found 0–6 people per frame, YOLOX-S (Accurate) 4–7, YOLOX-M on tiles 66 per frame with an ID on
average (52–80 for 80 % of frames, max 93) over the whole video. One frame takes about 5.5 s with ONNX Runtime here (about 11 s with OpenCV DNN):
ONNX Runtime ran YOLOX-M in 238 ms per 640 px input versus 472 ms for OpenCV DNN, with identical output.
