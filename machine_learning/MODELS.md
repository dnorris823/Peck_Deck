# Models & Taxonomy

Weights are **fetched, not committed** — they are third-party binaries with
their own licences. `machine_learning/*.tflite` and `*.pth` are gitignored.

```bash
python scripts/fetch_models.py     # Tier 1 weights (~3.5 MB), digest-checked
python scripts/build_taxonomy.py   # regenerate taxonomy.csv from the label map
python scripts/validate_tier1.py   # Tier 1 sanity check on 20 clean photos

# Field accuracy + calibration for both tiers (see "Measured accuracy" below)
python scripts/build_eval_set.py       # 300 iNaturalist field photos
python scripts/degrade_eval_set.py     # 9 feeder-camera degradations of each
python -m inference_server             # Tier 2 must be up to be measured
python scripts/validate_tiers.py --out report.json
python scripts/simulate_tier_chain.py report.json   # compare threshold settings
```

## The two CSVs are not interchangeable

| File | Rows | What it is |
|---|---|---|
| `taxonomy.csv` | 965 | **The model's label space.** Row *N* is output index *N*. Generated — never hand-edit. |
| `feeder_species.csv` | 20 | A curated North American backyard list, a subset of the above. Hand-maintained. |

`taxonomy.csv` is a contract, not a list of interesting birds:
`tier1_tflite.py` does `self._taxa[argmax]`, so a row inserted in the wrong
place mislabels every sighting while still looking entirely plausible. Regenerate
it with `build_taxonomy.py` whenever the model changes, and re-run
`validate_tier1.py` — a misaligned taxonomy scores near zero there, which is the
only cheap way to catch it.

`feeder_species.csv` exists because the simulator and demo draw from it. Drawing
from all 964 would put limpkins and cranes on the dashboard, and
`species_weights()` would hand "most common feeder bird" to whatever happens to
sit at index 0 of the model's label map.

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
bird. As written, a non-bird leaves every bird class low and the pipeline's
confidence threshold falls through to Tier 3 — which is the intended behaviour.

A model with no published `label_names` falls back to the legacy path: the head
is resized to the taxonomy and, without a `MODEL_PATH`, randomly initialised.
That path now logs a loud warning, because it is exactly the configuration that
produced meaningless labels through Phases 4a–4b.

## Measured accuracy

Both tiers score **20/20** on `validate_tier1.py`, which uses each species'
Wikipedia lead image. That is a genuine result and a useless one for predicting
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
cheaper. See `OUTDOOR_DEPLOYMENT.md` for where the camera actually goes.

### Calibration — the part that changes product behaviour

The pipeline escalates Tier 1 → 2 → 3 when confidence falls below
`CONFIDENCE_THRESHOLD` (0.5, in `raspberry_pi_code/config.py`). That design is
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
