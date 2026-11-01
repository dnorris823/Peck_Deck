# Models & Taxonomy

Weights are **fetched, not committed** — they are third-party binaries with
their own licences. `machine_learning/*.tflite` and `*.pth` are gitignored.

```bash
python scripts/fetch_models.py     # Tier 1 + bird detector weights, digest-checked
python scripts/build_taxonomy.py   # regenerate taxonomy.csv from the label map

# Field accuracy + calibration for both tiers (see "Measured accuracy" below)
python scripts/build_eval_set.py       # 300 iNaturalist field photos
python scripts/degrade_eval_set.py     # 9 feeder-camera degradations of each
python -m inference_server             # Tier 2 must be up to be measured
python scripts/validate_tiers.py --out report.json
python scripts/simulate_tier_chain.py report.json   # compare threshold settings

# Feeder animals: the detector and Tier 2 on squirrels, raccoons and cats
python scripts/build_eval_set.py --set animals --per-species 30
python scripts/degrade_eval_set.py --root .eval_animals
python scripts/validate_animals.py --out animals.json
```

## The two CSVs are not interchangeable

| File | Rows | What it is |
|---|---|---|
| `taxonomy.csv` | 965 | **The model's label space.** Row *N* is output index *N*. Generated — never hand-edit. |
| `feeder_species.csv` | 20 | A curated North American backyard list, a subset of the above. Hand-maintained. |
| `feeder_animals.csv` | 23 | Feeder mammals Tier 2 may name, each with its animal group. Hand-maintained. |

`taxonomy.csv` is a contract, not a list of interesting birds:
`tier1_tflite.py` does `self._taxa[argmax]`, so a row inserted in the wrong
place mislabels every sighting while still looking entirely plausible. Regenerate
it with `build_taxonomy.py` whenever the model changes, and re-run
`validate_tiers.py` — a misaligned taxonomy scores near zero there, which is the
only cheap way to catch it.

`feeder_species.csv` is the ground truth for the evaluation scripts. Scoring
against all 964 species would put limpkins and cranes in a backyard-feeder
benchmark.

`feeder_animals.csv` maps iNat21 scientific names to a group: squirrel,
chipmunk, raccoon, opossum, deer, bear, cat, rat, or rabbit. Red, gray, fox and
flying squirrels all map to `squirrel`. It never adds rows to `taxonomy.csv`,
because that file's row order is Tier 1's index contract. Every name in it must
be in Tier 2's `label_names`, or Tier 2 cannot predict it. The northern flying
squirrel, *Glaucomys sabrinus*, is not, so it is not listed.

## Tier 1 — on-device (Pi)

**Google AIY `birds_V1`** — MobileNetV2 trained on iNaturalist bird imagery.

| | |
|---|---|
| Source | Kaggle Models — `google/aiy/tfLite/vision-classifier-birds-v1/2` |
| Label map | `https://www.gstatic.com/aihub/tfhub/labelmaps/aiy_birds_V1_labelmap.csv` |
| Classes | 964 species + a `background` class (index 964) |
| Input / output | `[1,224,224,3]` uint8 → `[1,965]` uint8, quant scale `1/256` |
| Speed | 57.9 ms/inference on a Pi 5, 12 ms load |
| Accuracy | 20/20 on clean Wikipedia photos; **64.3%** on field photos |

The uint8 output *must* be dequantised — `tier1_tflite.py` applies the output
tensor's scale/zero-point. Without it `confidence` is a 0–255 integer and the
0.5 threshold is meaningless.

## Tier 2 — LAN GPU server (RTX 5080)

**`hf-hub:timm/vit_large_patch14_clip_336.laion2b_ft_augreg_inat21`** — ViT-L/14
fine-tuned on iNaturalist 2021, 10,000 species.

| | |
|---|---|
| Classes | 10,000 (all of iNat21 — plants and insects included) |
| Mapped onto `taxonomy.csv` | **869 of 965** (all 20 curated feeder species map) |
| Speed | 29.1 ms/inference, ~26 s cold load |
| Accuracy | 20/20 on clean Wikipedia photos; **85.0%** on field photos |

The two tiers share a label space by *projection*, not by architecture. The
checkpoint publishes `label_names` in its Hub `config.json`, so each output
index has a scientific name; `_build_projection` matches those against
`taxonomy.csv` and returns the taxonomy entry. This is what makes a Tier 1 and a
Tier 2 answer directly comparable.

**Softmax runs over all 10,000 classes, then the best *mapped* class is taken.**
Restricting before the softmax would renormalise a squirrel into a confident
bird. A non-bird leaves every bird class low.

The same softmax also gives the best row of `feeder_animals.csv`. `POST /classify`
returns it as `animal`, with `common_name`, `scientific_name`, `group` and
`confidence`, or null. The bird fields do not change, so an old Pi build reads
them as before. The Pi records an animal sighting when the animal's confidence
meets `TIER2_ANIMAL_THRESHOLD` and beats the best bird. Tier 1 and Tier 3 then
never run, because Tier 1 knows birds only and Tier 3 costs money.

A model with no published `label_names` falls back to the legacy path: the head
is resized to the taxonomy and, without a `MODEL_PATH`, randomly initialised.
That path now logs a loud warning, because it is exactly the configuration that
produced meaningless labels through Phases 4a–4b.

## Camera trigger detector (Pi)

**EfficientDet-Lite0**, COCO-trained, with TFLite post-processing built in. It
does not name the species. It answers one question: is there a bird in the
frame. Tier 2 names the species after the capture.

| | |
|---|---|
| Source | Kaggle Models, `tensorflow/efficientdet/tfLite/lite0-detection-metadata/1` |
| File | `machine_learning/efficientdet_lite0_detection.tflite`, from `fetch_models.py` |
| Input | `[1,320,320,3]` uint8 |
| Outputs | boxes `[1,25,4]`, classes `[1,25]`, scores `[1,25]`, count `[1]`, all float32 |
| Bird class | 15 (the embedded `labelmap.txt` starts at person = 0) |
| Speed | 11.7 ms/frame on the gaming PC CPU. Not yet measured on the Pi 5 |

Per-frame bird recall on the 300-photo field set and its degradations. The
numbers come from `BirdDetector.detect` on each photo, with the score threshold
swept. Each row is one frame per photo.

| Variant | @0.3 | @0.4 | **@0.5** | @0.6 |
|---|---:|---:|---:|---:|
| `clean` | 76.3% | 68.7% | **62.0%** | 50.7% |
| `off_center` | 79.0% | 75.0% | **64.3%** | 55.0% |
| `motion_blur` | 72.0% | 64.7% | **57.0%** | 43.7% |
| `low_light` | 65.3% | 60.3% | **53.3%** | 42.0% |
| `distant` | 53.7% | 44.3% | **35.7%** | 24.3% |
| `field_combo` | 29.0% | 23.7% | **18.0%** | 11.3% |

Blank frames (black, grey, white, a gradient, random noise) score 0.012 at most.

`CAMERA_DETECTION_THRESHOLD` defaults to 0.5. Per-frame recall understates
per-visit recall, because the trigger checks several frames a second for as long
as the bird moves. A false positive costs more than one missed frame, since it
uploads a sighting of an empty feeder. This set has no hand photos, so the
false-positive rate on real scenes is not measured yet. What the detector does
with a squirrel is under *Feeder animals* below.

Feeding the frame as BGR instead of RGB costs about 5 points (`clean` 62.0% to
57.3% at 0.5). `PiCamera` asks picamera2 for `BGR888`, which is its name for an
`[R, G, B]` array.

## Measured accuracy

Both tiers scored **20/20** on the old Wikipedia lead-image check (since
removed). That was a genuine result and a useless one for predicting
field behaviour: an encyclopedia lead image is a bird photographer's keeper shot,
and a feeder camera gets a third-of-frame bird behind a perch, mid-wingbeat, in
whatever light dawn offers.

The field set is 300 research-grade iNaturalist observations — 15 for each of the
20 curated feeder species, sampled at random, one per observer, restricted to
2022 or later so that Tier 2 (fine-tuned on iNat21) is not being scored on its
own training data. Each photo is then degraded nine ways, one property at a time,
so the results form an ablation rather than a single "it does worse" number.
Rebuild it with `build_eval_set.py` + `degrade_eval_set.py`; measure with
`validate_tiers.py`, which drives the real Pi clients over the real wire.

### Top-1 accuracy

| Variant | What it simulates | Tier 1 | Tier 2 |
|---|---|---:|---:|
| *Wikipedia* | *the old benchmark* | *100%* | *100%* |
| `clean` | **real field photo, undegraded** | **64.3%** | **85.0%** |
| `off_center` | bird pushed to frame edge | 69.0% | 81.7% |
| `motion_blur` | wingbeat / hop smear | 61.0% | 82.7% |
| `sensor_soft` | detail loss at 1080p | 61.0% | 77.3% |
| `jpeg_lossy` | aggressive recompression | 60.7% | 77.7% |
| `backlit` | bird against a bright sky | 53.7% | 79.7% |
| `low_light` | dawn / dusk + sensor noise | 50.3% | 74.3% |
| `occluded` | feeder pole or perch in the way | 46.3% | 69.3% |
| `distant` | bird small in frame | **30.3%** | **56.3%** |
| `field_combo` | distant + blurred + dark + compressed | 16.7% | 28.3% |

**Subject size dominates every other factor.** `distant` roughly halves both
tiers, while blur, compression and softness barely move them. The corroborating
detail is `off_center`, the only variant that *improves* Tier 1 (64.3% → 69.0%):
cropping toward a corner discards frame but enlarges what is left, and the gain
from a bigger bird outweighs the loss from clipping it. Both results say the same
thing — what matters is how many pixels land on the bird.

That is a mounting decision, not a modelling one. A camera placed so a chickadee
fills a good part of the frame is worth more than any amount of tuning, and it is
cheaper. See `docs/archive/OUTDOOR_DEPLOYMENT.md` for where the camera actually goes.

### Calibration — the part that changes product behaviour

The pipeline escalates to the next tier when confidence falls below a threshold.
It used to use one global `CONFIDENCE_THRESHOLD` of 0.5 for every tier. That
setting is gone, and each tier now has its own threshold. The design is
only sound if wrong answers arrive with *low* confidence. A tier that is
confidently wrong never escalates: the app shows the wrong bird, as fact, with
nothing anywhere indicating doubt.

Pooled over all 3,000 images, of the answers each tier **accepts** at a given
threshold, this many are wrong:

| Threshold | Tier 1 accepted | Tier 1 wrong-and-accepted | Tier 2 accepted | Tier 2 wrong-and-accepted |
|---:|---:|---:|---:|---:|
| 0.30 | 64.1% | 28.1% | 62.9% | 8.5% |
| **0.50** *(current)* | **49.2%** | **18.2%** | **52.8%** | **5.3%** |
| 0.70 | 38.7% | 12.1% | 40.4% | 2.1% |
| 0.85 | 27.4% | 8.2% | 24.9% | 1.2% |

**At the shipped threshold, nearly one in five Tier 1 answers that the pipeline
accepts is the wrong species.** Nothing escalates, so nothing catches it. Tier 2
at the same threshold is wrong on 5.3% of what it accepts, and its confidence on
wrong answers averages 0.242 against Tier 1's 0.368 — Tier 1 is not merely less
accurate, it is *less honest about being wrong*, which is the more damaging of
the two properties.

**One global threshold is the wrong shape for this pipeline**, for two
independent reasons:

- The tiers' confidences are not comparable. Tier 2 softmaxes over 10,000
  classes, so its scores are structurally lower than Tier 1's over 965 — the
  same number means something different in each.
- The escalations do not cost the same. Tier 1 → Tier 2 is a ~26 ms LAN round
  trip to a GPU that is already running; Tier 2 → Tier 3 is a paid Claude API
  call. Tier 1 should escalate eagerly and Tier 2 reluctantly, which a single
  constant cannot express.

**Now implemented** — `DEFAULT_TIER_THRESHOLDS` in `raspberry_pi_code/config.py`
ships **0.85 for Tier 1, 0.60 for Tier 2, 0.50 for Tier 3**, overridable per tier
via `TIER1_/TIER2_/TIER3_CONFIDENCE_THRESHOLD`.

The numbers above score each tier alone; what a user actually gets is whatever
the *chain* settles on. `scripts/simulate_tier_chain.py` replays the real
escalation logic over the same 3,000 images:

| Tier 1 / Tier 2 | Accepted | Wrong and accepted | Final top-1 |
|---|---:|---:|---:|
| 0.50 / 0.50 *(old)* | 65.8% | **16.0%** (315) | 65.0% |
| **0.85 / 0.60** *(shipped)* | 53.9% | **6.9%** (112) | **68.3%** |
| 0.85 / 0.50 | 58.1% | 7.9% (137) | 68.9% |
| 0.90 / 0.60 | 51.7% | 5.6% (87) | 68.7% |

**Silent errors fall by 64% and accuracy goes up**, because the captures Tier 1
stops claiming are handed to a tier that is better at them. There is no accuracy
cost to pay for the honesty; the only cost is LAN round trips.

The last two rows are the honest tension. `0.85 / 0.50` is fractionally more
accurate (68.9%) but accepts 25 more wrong answers; the shipped pair prefers
fewer silent errors, on the grounds that a wrong species stated as fact is worse
than a right one arrived at through one more hop. Tier 3 is absent from this
replay, so where `CLAUDE_API_KEY` *is* set the accuracy column is a floor — a
real Tier 3 call can only improve on the best-effort answer it replaces.

### Feeder animals

Measured on 2026-11-01 with `scripts/validate_animals.py`. The set is 30
research-grade iNaturalist photos each of six mammals, observed on or after
2022-01-01, one photo per observer. That is 180 clean photos, and 1,800 with the
nine degradations. The bird set is the 300 field photos above and their
degradations, 3,000 photos in all. Tier 2 sees the full frame, because a squirrel
the detector misses has no box to crop to.

**The detector misses most animals.** EfficientDet-Lite0 has no squirrel class.
The table gives the share of clean photos where each COCO class scores 0.5 or
more, which is `CAMERA_DETECTION_THRESHOLD`. "Any" is bird, cat, dog or bear.

| Species | n | bird | cat | dog | bear | any |
|---|---:|---:|---:|---:|---:|---:|
| Eastern gray squirrel | 30 | 20.0% | 3.3% | 0.0% | 6.7% | 30.0% |
| American red squirrel | 30 | 13.3% | 3.3% | 3.3% | 6.7% | 26.7% |
| Eastern chipmunk | 30 | 10.0% | 10.0% | 3.3% | 6.7% | 30.0% |
| Raccoon | 30 | 3.3% | 10.0% | 3.3% | 20.0% | 36.7% |
| Virginia opossum | 30 | 3.3% | 20.0% | 6.7% | 3.3% | 33.3% |
| House cat | 30 | 6.7% | 50.0% | 3.3% | 0.0% | 56.7% |
| **All clean** | 180 | 9.4% | 16.1% | 3.3% | 7.2% | **35.6%** |

Across the degraded variants "any" falls to between 8.3% (`field_combo`) and
38.9% (`off_center`). Half the clean photos score no class at 0.5 at all. So the
bird-only trigger catches about one squirrel photo in six. Firing on bird, cat,
dog and bear catches about one in three. The trigger now fires on those four,
`ANIMAL_CLASS_IDS`. A trigger that must see most squirrels needs the motion
fallback, `CAMERA_MOTION_CAPTURE`, or a detector with an animal class.

**Tier 2 names animals well, and never names a bird as one.** "Group ok" is the
share where the best listed animal is in the right group, at any confidence. The
other columns are the share recorded as the right group under the Pi's rule,
which needs the animal to meet the bar and beat the best bird.

| Species | n | group ok | median conf | @0.3 | @0.5 |
|---|---:|---:|---:|---:|---:|
| Eastern gray squirrel | 30 | 100.0% | 0.78 | 83.3% | 76.7% |
| American red squirrel | 30 | 100.0% | 0.88 | 93.3% | 83.3% |
| Eastern chipmunk | 30 | 100.0% | 0.88 | 93.3% | 90.0% |
| Raccoon | 30 | 83.3% | 0.64 | 63.3% | 60.0% |
| Virginia opossum | 30 | 86.7% | 0.89 | 76.7% | 70.0% |
| House cat | 30 | 90.0% | 0.79 | 73.3% | 73.3% |
| **All clean** | 180 | 93.3% | 0.84 | **80.6%** | 75.6% |

| Bar | Animals recorded, clean | Wrong group, clean | Wrong group, all 1,800 | Birds recorded as animals, all 3,000 |
|---:|---:|---:|---:|---:|
| 0.2 | 86.1% | 3 | 23 (1.8% of accepted) | 0 |
| **0.3** | **80.6%** | **0** | **11 (0.9%)** | **0** |
| 0.4 | 77.8% | 0 | 3 (0.3%) | 0 |
| 0.5 | 75.6% | 0 | 1 (0.1%) | 0 |

The highest animal confidence Tier 2 gave any of the 3,000 bird photos was 0.088.

`TIER2_ANIMAL_THRESHOLD` defaults to **0.30**. It sits more than three times
above the worst bird, and it records 80.6% of clean animal photos with no wrong
group. A higher bar costs squirrels for little gain. An animal that misses the
bar goes down the bird chain, and none of the 35 that missed at 0.30 had a Tier 2
bird at 0.60 or more. So each one falls to Tier 1, which can accept a wrong bird.
A wrong animal group is the cheaper mistake.

`distant` and `field_combo` hurt Tier 2 the most here too: 35.6% and 18.3% recorded
at 0.5. The Pi crops to the detector's box when there is one, which should help
the distant case. That is not measured.

### What this measurement still is not

The photos are field shots, but they are still photographs a person chose to
take and upload, of a bird they could see well enough to photograph. A
motion-triggered camera has no such filter: it fires on a bird facing away, or
half out of frame, or already leaving. **These numbers remain an upper bound**,
merely a much closer one than 20/20. The honest measure is still a real field
test, which is what Phase 4 is for.

Sample size is 15 photos per species, so per-species figures move by ~7 points
per photo and should be read as indicative. The `off_center` and `occluded`
variants are applied without knowing where the bird is, so both are
pessimistically biased on the fraction of images where they clip it hard.

## Naming conventions

- Common names come from Wikipedia article titles (a binomial redirects to its
  English name), title-cased to ornithological convention: `Black-capped
  Chickadee`, not `Black-Capped`. Coverage is 963/964.
- Where the curated list overlaps, **its** names win. Wikipedia prefers the
  global IOC name, which would silently rename `European Starling` to `Common
  Starling` across the app and the seed data.
- The model's label map is frozen at ~2023 iNaturalist naming. `CURRENT_NAMES`
  in `build_taxonomy.py` records renames (e.g. `Picoides pubescens` →
  `Dryobates pubescens`) so the CSV shows today's name while the row stays at
  the index the model actually emits.
