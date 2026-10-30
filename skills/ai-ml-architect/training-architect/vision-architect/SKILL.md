---
name: vision-architect
description: Architect-level computer vision design — task framing (classification, detection, segmentation, OCR), pretrained versus custom training, data collection and labelling strategy, augmentation, edge versus server inference, and the evaluation and monitoring that catches model decay in images. Use when images or video must be interpreted.
license: MIT
compatibility: YOLO, Detectron2, torchvision, cloud vision APIs, OpenCV
metadata:
  crusor-domain: ai-ml-architect
  crusor-path: ai-ml-architect/training-architect/vision-architect
  crusor-origin: original
  crusor-sources: "pytorch.org/vision/stable; docs.ultralytics.com; cloud.google.com/vision/docs; arxiv.org/abs/2010.11929"
  crusor-triggers: "computer vision, image classification, object detection, segmentation, ocr, yolo, image model, video analysis, annotation"
  crusor-verified-on: "2026-10-30"
---

# Vision Architect

Vision projects fail on **data and problem framing** far more often than on model
architecture. Start with what decision the pixels drive.

## When to use

- Image/video classification, detection, segmentation, OCR, quality inspection.
- Document understanding from scans.
- Visual search or content moderation.

## When NOT to use

- The label can be derived from metadata you already have.
- A hosted API meets the accuracy bar — build nothing.

## Decision 1 — Frame the task

| Task | Output | Cost |
|---|---|---|
| classification | one label per image | cheapest |
| detection | boxes + labels | moderate |
| segmentation | pixel masks | expensive |
| OCR/document | text + layout | moderate |
| retrieval | embedding similarity | cheap to serve |

- Start one level simpler than you think you need; detection is often avoidable.
- Define the acceptance criterion numerically: mAP@0.5, F1 per class, character
  error rate — before data collection.

## Decision 2 — Build or buy

- Hosted APIs for generic tasks (OCR, moderation, logo/object detection) unless the
  domain is unusual.
- Pretrained backbones fine-tuned on your data for domain-specific tasks — rarely
  train from scratch.
- Self-host when latency, volume, privacy, or per-image cost demands it, and only
  with the ops capacity for GPU serving (`gpu-capacity-architect`).

## Decision 3 — Data

- Collect for the **deployment distribution**: same cameras, lighting, angles,
  devices, and compression.
- Labelling guidelines with positive/negative examples and an adjudication path for
  ambiguous cases.
- Measure inter-annotator agreement; low agreement means the task is ill-defined,
  not the model weak.
- Class balance: rare classes need deliberate collection, not oversampling alone.
- Hold out entire sites/devices/days to test generalisation, not just random images.

## Decision 4 — Training

- Augmentation matched to real variation (lighting, crop, blur, rotation) — but not
  so aggressive it creates impossible inputs.
- Track per-class metrics; aggregate mAP hides the class that fails.
- Evaluate on the hardest slice: night, rain, low resolution, occluded.
- Version datasets and training configs; images are heavy, so record hashes and
  storage locations.

## Decision 5 — Serving

- Preprocess exactly as in training (resize, colour space, normalisation) — the most
  common production bug.
- Edge inference for latency/privacy, server for accuracy and central updates;
  hybrid with on-device gating is common.
- Batch inference offline for large archives.
- Log a sample of inputs and predictions for monitoring (with privacy controls).

## Decision 6 — Monitoring

- Input drift: brightness, blur, resolution, camera changes.
- Prediction drift: class distribution shifts, confidence collapse.
- Human-in-the-loop review of low-confidence predictions, feeding the next dataset.
- Shadow mode before switching a decision to the model.

## Failure modes at scale

- Trained on studio images, deployed on phone photos; accuracy halves.
- OCR used as a general document parser, ignoring layout.
- Class imbalance handled by oversampling alone; the rare class still fails.
- Aggregated mAP hides a class at 0.2; a downstream decision breaks.
- Training preprocessing differs from serving; predictions are noise.

## Verification receipts

1. Task framing with the numeric acceptance criterion.
2. Dataset card: sources, counts per class, labelling guidelines, splits.
3. Evaluation per class and per hard slice.
4. Preprocessing parity test between training and serving.
5. Drift dashboard with alert thresholds for the sample of logged inputs.
