# picamera2 focus lock and shutter floor on IMX708 (issue #39)

## The question

`raspberry_pi_code/camera/pi_camera.py` opens the camera with no autofocus or
exposure configuration at all:

```python
cfg = self._cam.create_still_configuration(main={"size": (self._width, self._height)})
self._cam.configure(cfg)
self._cam.start()
```

The upcoming accuracy test shoots the Camera Module 3 (IMX708) through a
window at one fixed distance. If the lens is free to hunt, or the shutter is
free to lengthen in low light, frames can be soft/motion-blurred in a way
that would corrupt the ML accuracy measurement (`MODELS.md` already documents
that Tier 1/2 accuracy claims must come from realistic field photos, not
clean ones). This note establishes **what the picamera2/libcamera API can
do** for locking focus once and flooring/capping the shutter — not the actual
numeric distance or exposure values, which belong to a separate tuning
ticket.

Everything below is sourced from the libcamera control specification, the
picamera2 source code and test suite, the Raspberry Pi camera tuning file for
the IMX708, and the official Raspberry Pi documentation/manual — not blogs or
forum threads. Where a forum thread pointed me somewhere useful, I verified
the underlying claim against the code or spec before using it.

---

## 1. Locking focus on IMX708 via picamera2

### `AfMode`, `AfTrigger`, `AfState`, `AfPauseState` — values and semantics

These are libcamera **core** controls (not Pi-specific), defined in
`control_ids_core.yaml`:

- **`AfMode`** (int32, in/out) — 3 values:
  - `AfModeManual` (0): "the AF algorithm ... will never perform any action
    nor move the lens of its own accord, but an application can specify the
    desired lens position using the `LensPosition` control. The `AfState`
    will always report `AfStateIdle`." The spec calls this **"the
    recommended default value for the `AfMode` control."**
  - `AfModeAuto` (1): the lens never moves except in response to
    `AfTrigger`. Sending `AfTrigger`/`AfModeAuto` together skips straight to
    `AfStateScanning`.
  - `AfModeContinuous` (2): "the lens can re-start a scan spontaneously at
    any moment, without any user intervention" — this is the mode that
    "hunts." It can be paused via `AfPause` without switching modes.
  [libcamera `control_ids_core.yaml`](https://github.com/raspberrypi/libcamera/blob/main/src/libcamera/control_ids_core.yaml)

- **`AfTrigger`** (int32, in) — `AfTriggerStart` (0) / `AfTriggerCancel` (1).
  **"This control ... is ignored if `AfMode` is set to `AfModeManual` or
  `AfModeContinuous`."** — i.e. it only does anything in `AfModeAuto`.
  [same file]

- **`AfState`** (int32, out; read-only, comes back in per-frame metadata) —
  `AfStateIdle` (0) / `AfStateScanning` (1) / `AfStateFocused` (2) /
  `AfStateFailed` (3). In `AfModeManual` it "will always report
  `AfStateIdle` (even if the lens is subsequently moved)."
  [same file]

- **`AfPauseState`** (int32, out) — only meaningful in `AfModeContinuous`:
  `Running` / `Pausing` / `Paused`, driven by the separate `AfPause` control.
  Not needed for a one-shot lock, but useful if a later Tier-1 change wants
  live continuous AF with a "hold still while I capture" pause instead of a
  hard mode switch.
  [same file]

### `LensPosition` units and the distance conversion

**`LensPosition` (float, in/out) is in dioptres — the reciprocal of focal
distance in metres.** Quoting the control spec directly:

> "This value, which is generally a non-integer, is the reciprocal of the
> focal distance in metres, also known as dioptres. That is, to set a focal
> distance D, the lens position LP is given by LP = 1m / D.
> - 0 moves the lens to infinity.
> - 0.5 moves the lens to focus on objects 2m away.
> - 2 moves the lens to focus on objects 50cm away.
> - And larger values will focus the lens closer."

[libcamera `control_ids_core.yaml` — `LensPosition`](https://github.com/raspberrypi/libcamera/blob/main/src/libcamera/control_ids_core.yaml)

So the conversion for this codebase is simply `lens_position = 1.0 / distance_metres`
(with `0.0` meaning infinity). The control is a **write** to command a move
and simultaneously a **read** in image metadata reporting where the lens
actually is; it "is ignored unless `AfMode` is set to `AfModeManual`, though
the value is reported back unconditionally in all modes" — i.e. setting
`LensPosition` while in `AfModeAuto`/`AfModeContinuous` silently does nothing
to the lens, it just keeps reporting the AF algorithm's own position back to
you. This is a documented silent no-op that matters for the lifecycle
section below.

The IMX708's own tuning file gives the concrete range for this sensor
(Camera Module 3, non-wide, on a Pi 5 — the `pisp` pipeline):

```json
"rpi.af": {
  "ranges": {
    "normal": { "min": 0.0, "max": 12.0, "default": 1.0 },
    "macro":  { "min": 3.0, "max": 15.0, "default": 4.0 }
  }, ...
```
[`src/ipa/rpi/pisp/data/imx708.json`](https://github.com/raspberrypi/libcamera/blob/main/src/ipa/rpi/pisp/data/imx708.json)

i.e. on this module, `LensPosition` runs from `0.0` (infinity) to `12.0`
(~8 cm) in the "normal" AF range, and the tuning file's own default parked
position is `1.0` dioptre (1 metre) — not infinity.

### What AfMode does the camera actually start in?

The RPi AF algorithm's own default, at C++ construction time, is
**`AfModeManual`**:

```cpp
mode_(AfAlgorithm::AfModeManual),
```
[`src/ipa/rpi/controller/rpi/af.cpp`, line 178](https://github.com/raspberrypi/libcamera/blob/main/src/ipa/rpi/controller/rpi/af.cpp)

and I found nothing in the pipeline handler (`src/ipa/rpi/common/ipa_base.cpp`)
that overrides this at camera-open time — `AfMode` is registered as an
advertised control with no separate default injection. So a bare
`Picamera2()` with no controls set (exactly what `pi_camera.py` does today)
should, per the libcamera/IMX708 tuning defaults, come up in **manual** mode
parked at **1.0 dioptre (1 m)**, not scanning.

This is worth flagging against the ticket's framing ("the lens hunts"): the
one place I found an *explicit* default of continuous AF is in
**rpicam-apps** (the separate C++ CLI, not the Picamera2 Python library):

> "`--autofocus-mode` ... default: normally puts the camera into continuous
> autofocus mode, except if either `--lens-position` or
> `--autofocus-on-capture` is given, in which case manual mode is chosen
> instead."
[raspberrypi/documentation, `rpicam_options_common.adoc`](https://github.com/raspberrypi/documentation/blob/master/documentation/asciidoc/computers/camera/rpicam_options_common.adoc)

`pi_camera.py` calls the Picamera2 Python API directly and never shells out
to rpicam-apps, so that convenience default shouldn't apply here — but I
could not rule out, from source alone, some other layer (an OS camera
default, a different picamera2/libcamera build than what I read on `main`)
producing continuous-AF behavior in practice. See **Open uncertainties**.
Regardless of which default is actually in effect, the fix is the same:
**stop relying on any default and pin `AfMode` explicitly.**

### The "autofocus once, then hold" pattern — yes, it's a documented helper

`Picamera2` has a purpose-built method for exactly this, `autofocus_cycle()`,
and it is documented in the official manual as the recommended way to
trigger one scan:

> "For triggering an autofocus cycle in Auto mode, we recommend using a
> helper function that monitors the autofocus algorithm state for you ...
> `success = picam2.autofocus_cycle()`"
[Picamera2 manual (PDF)](https://datasheets.raspberrypi.com/camera/picamera2-manual.pdf)

Its actual implementation (current `main`):

```python
def autofocus_cycle(self, wait=None, signal_function=None) -> Union[bool, Job[bool]]:
    """Switch autofocus to auto mode and run an autofocus cycle.

    Return True if the autofocus cycle focuses successuly, otherwise False.
    """
    self.set_controls({"AfMode": controls.AfModeEnum.Auto, "AfTrigger": controls.AfTriggerEnum.Start})

    def wait_for_af_state(self, states):
        if not self.completed_requests:
            return (False, None)
        af_state = self.completed_requests[0].get_metadata()['AfState']
        self.completed_requests.pop(0).release()
        return (af_state in states, af_state == controls.AfStateEnum.Focused)

    # First wait for the scan to start. Once we've seen that, the AF cycle may:
    # succeed, fail or could go back to idle if it is cancelled.
    functions = [
        partial(wait_for_af_state, self, {controls.AfStateEnum.Scanning}),
        partial(wait_for_af_state, self, {controls.AfStateEnum.Focused, controls.AfStateEnum.Failed, controls.AfStateEnum.Idle}),
    ]
    return self.dispatch_functions(functions, wait, signal_function)
```
[`picamera2/picamera2.py`, `autofocus_cycle`](https://github.com/raspberrypi/picamera2/blob/main/picamera2/picamera2.py)

Important detail: **`autofocus_cycle()` itself leaves `AfMode` in `Auto`,
not `Manual`, after it returns.** It switches to `Auto`, triggers a scan, and
waits for the state machine to leave `Scanning`. It does *not* re-freeze the
lens for you. `AfModeAuto` alone won't spontaneously hunt again (per the
`AfMode` spec above), but it's one stray `AfTrigger` call away from doing so.
The robust "freeze so it can never hunt again" pattern — confirmed by
reading the lens position back out of metadata and then switching to
`AfModeManual` with that value — is exactly what the corresponding picamera2
test does:

```python
picam2.set_controls({'AfMode': controls.AfModeEnum.Manual, 'LensPosition': i})
time.sleep(0.5)
lp = picam2.capture_metadata()['LensPosition']
...
result = picam2.autofocus_cycle()
```
[`tests/autofocus_test.py`](https://github.com/raspberrypi/picamera2/blob/main/tests/autofocus_test.py)

and the shipped example app that runs one AF cycle before a still capture:
[`apps/app_capture_af.py`](https://github.com/raspberrypi/picamera2/blob/main/apps/app_capture_af.py)
calls `picam2.autofocus_cycle(signal_function=...)`, waits on the job, then
proceeds to capture — note in that example the camera is already `start()`ed
before `autofocus_cycle()` is called; the AF cycle is a post-`start()`
operation, not something you can run at configure time.

So the concrete, primary-sourced recipe is:

1. `picam2.set_controls({"AfMode": AfModeEnum.Auto})` (or skip — `autofocus_cycle()` sets this for you).
2. `focused = picam2.autofocus_cycle()` — blocks (by default) until `AfState` leaves `Scanning`; returns `True` only if it lands on `Focused`.
3. Read back the converged position: `lens_position = picam2.capture_metadata()["LensPosition"]`.
4. Freeze it: `picam2.set_controls({"AfMode": AfModeEnum.Manual, "LensPosition": lens_position})`.

After step 4, per the `AfMode`/`AfTrigger` spec quoted above, the lens
"will never move spontaneously" and any stray `AfTrigger` is silently
ignored — this is the strongest guarantee available, stronger than leaving
it in `AfModeAuto`.

### Checking AF is even present

Not every camera module has a focus motor. The documented guard, used in
both the test suite and the example app, is:

```python
if 'AfMode' not in picam2.camera_controls:
    print("Attached camera does not support autofocus")
```
[`apps/app_capture_af.py`](https://github.com/raspberrypi/picamera2/blob/main/apps/app_capture_af.py),
[`tests/autofocus_test.py`](https://github.com/raspberrypi/picamera2/blob/main/tests/autofocus_test.py)

`camera_controls` is populated from the sensor's advertised control list, so
this also doubles as a no-op-safe guard for `pi_camera.py`'s dev-machine
fallback path (where `self._cam` doesn't exist at all today, but even on a
future non-CM3 module this check prevents crashing on `AfMode`).

---

## 2. Shutter floor / motion freeze

### The controls, verbatim from the libcamera core spec

- **`ExposureTime`** (int32, in/out, µs): "This control will only take
  effect if `ExposureTimeMode` is Manual. If this control is set when
  `ExposureTimeMode` is Auto, the value will be ignored and will not be
  retained."
- **`AeEnable`** (bool, in): "When this control is set to true, both
  `ExposureTimeMode` and `AnalogueGainMode` are set to auto, and if this
  control is set to false then both are set to manual. If `ExposureTimeMode`
  or `AnalogueGainMode` are also set in the same request as `AeEnable`, then
  the modes supplied ... will take precedence."
- **`AeConstraintMode`**: `ConstraintNormal` (0, default — balances exposure
  across the frame), `ConstraintHighlight` (1 — protects bright areas),
  `ConstraintShadows` (2 — protects dark areas), `ConstraintCustom` (3).
  This tunes *which parts of the scene* AE optimises for; it does not floor
  or cap the shutter by itself.
- **`AnalogueGain`** (float, in/out): "cannot be lower than 1.0 ... will only
  take effect if `AnalogueGainMode` is Manual."
- **`FrameDurationLimits`** (int64×2, in/out, µs — `[min, max]`): "the
  control specifies the sensor frame duration interval the pipeline has to
  use. This limits the largest exposure time the sensor can use ... A fixed
  frame duration is achieved by setting the minimum and maximum values to be
  the same ... **The maximum frame duration provides the absolute limit to
  the exposure time computed by the AE algorithm and it overrides any
  exposure mode setting** ... when a manual exposure time is set through
  `ExposureTime`, it also gets clipped to the limits set by this control."

[libcamera `control_ids_core.yaml`](https://github.com/raspberrypi/libcamera/blob/main/src/libcamera/control_ids_core.yaml)

- **`ExposureTimeMode`** / **`AnalogueGainMode`** (int32, in/out — both
  `Auto`=0 / `Manual`=1) are a **newer, more granular split** of what
  `AeEnable` used to control as one on/off pair — they let exposure time and
  gain be put in manual mode independently. These landed in libcamera as a
  multi-patch series through 2025 (e.g.
  ["controls: Redefine AeEnable"](https://patchwork.libcamera.org/patch/22556/),
  ["controls: Reorganize the AE-related controls"](https://patchwork.libcamera.org/patch/15179/)).
  [same core yaml file]
- **`AeExposureMode`** (int32, in/out): `ExposureNormal` (0, default),
  `ExposureShort` (1, "allowing only short exposure times"), `ExposureLong`
  (2), `ExposureCustom` (3). Docs: "the exposure modes specify how the
  desired total exposure is divided between the exposure time and the
  sensor's analogue gain ... When one of `AnalogueGainMode` or
  `ExposureTimeMode` is set to Manual, the fixed values will override any
  choices made by `AeExposureMode`." [same core yaml file]

### Can you floor the shutter with AE still on, or does it require going fully manual?

**Both are possible, and they answer slightly different questions:**

1. **Keep AE fully on, just cap the exposure-time ceiling:**
   `FrameDurationLimits` does this directly and is explicit in the spec that
   it "overrides any exposure mode setting" and "provides the absolute
   limit to the exposure time computed by the AE algorithm" — AE keeps
   running (both exposure time and gain still auto-adjust), it just can't
   push the shutter past what the frame-duration ceiling allows. This is the
   right tool for "let AE do its job, but never let it go slower than X".
   Set it with `min == max` for a fixed frame rate, or `min < max` to just
   cap the slow end while leaving the fast end free.

2. **Bias AE toward short exposures without fully disabling it:**
   `AeExposureMode: ExposureShort` — still fully automatic (AE stays on),
   but the AE algorithm draws from a shutter/gain table biased toward
   shorter exposure times (see the IMX708 tuning file quote below). This is
   softer than (1): it's a preference, not a hard ceiling.

3. **Go fully manual:** set `AeEnable: False` (classic API) or explicitly
   set `ExposureTimeMode`/`AnalogueGainMode` to `Manual` (current API) and
   supply `ExposureTime`/`AnalogueGain` values yourself. Only in this mode
   does `ExposureTime` actually take effect per its own spec text quoted
   above — **setting `ExposureTime` while auto-exposure is still driving it
   is a documented silent no-op** ("the value will be ignored and will not
   be retained").

Note one CLI-level data point that corroborates (2)/(3) coexisting in
practice — rpicam-apps' `--shutter` option description:

> "Specifies the exposure time, using the shutter, in microseconds. Gain can
> still vary when you use this option."
[raspberrypi/documentation, `rpicam_options_common.adoc`](https://github.com/raspberrypi/documentation/blob/master/documentation/asciidoc/computers/camera/rpicam_options_common.adoc)

i.e. even rpicam-apps' idea of "fix the shutter" leaves gain free by
default — a middle ground between fully-auto and fully-manual, and something
`FrameDurationLimits` + free-running AE for gain gives you directly via the
picamera2 API.

**Picamera2 currently auto-derives the new mode controls for you** at
`start()` time, based on whatever `ExposureTime`/`AnalogueGain` values you
handed it (this is in the current `main` branch — see version caveat in
Open Uncertainties):

```python
def start_(self):
    ...
    controls = self.controls.get_libcamera_controls()

    # The latest libcamera requires is to set "ExposureTimeMode" to manual if we are setting
    # a fixed value, or to "auto" if we're going back to auto mode.
    exposure_time = controls.get(libcamera.controls.ExposureTime, None)
    if exposure_time is not None:
        controls[libcamera.controls.ExposureTimeMode] = 0 if exposure_time == 0 else 1

    # Ditto for the analogue gain.
    analogue_gain = controls.get(libcamera.controls.AnalogueGain, None)
    if analogue_gain is not None:
        controls[libcamera.controls.AnalogueGainMode] = 0 if analogue_gain == 0 else 1

    self.controls = Controls(self)
    self.camera.start(controls)
```
[`picamera2/picamera2.py`, `start_`](https://github.com/raspberrypi/picamera2/blob/main/picamera2/picamera2.py)

This is only exercised at the *very first* `start()` call (it reads whatever
was accumulated in `self.controls` up to that point and bakes it into the
one `camera.start(controls)` call — see the lifecycle section for why that
matters). It's also consistent with the shipped
[`examples/exposure_fixed.py`](https://github.com/raspberrypi/picamera2/blob/main/picamera2/../examples/exposure_fixed.py):

```python
controls = {"ExposureTime": 10000, "AnalogueGain": 1.0}
preview_config = picam2.create_preview_configuration(controls=controls)
picam2.configure(preview_config)
picam2.start()
```

— no explicit `AeEnable`/mode control at all; passing non-zero
`ExposureTime`/`AnalogueGain` is sufficient on current picamera2 to force
manual mode for both at start.

### Gain/noise behaviour when the shutter is floored (capped)

The IMX708 tuning file's own AGC ("AEGC") tables give a directly primary
answer to "what happens to gain when I can't lengthen the shutter any
further": the algorithm has paired `shutter`/`gain` arrays that it walks
along together as the scene gets darker. For the Pi 5 (`pisp`) IMX708,
"normal" exposure mode:

```json
"exposure_modes": {
  "normal": {
    "shutter": [ 100, 10000, 30000, 50000, 66666 ],
    "gain":    [ 1.0, 1.5,   2.0,   4.0,   16.0   ]
  },
  "short": {
    "shutter": [ 100, 5000, 10000, 20000, 60000 ],
    "gain":    [ 1.0, 1.5,  2.0,   4.0,   16.0   ]
  },
  ...
```
[`src/ipa/rpi/pisp/data/imx708.json`](https://github.com/raspberrypi/libcamera/blob/main/src/ipa/rpi/pisp/data/imx708.json)

Reading this as intended (AEGC extends shutter through the table's shutter
values first, and only escalates gain once shutter is maxed for the current
brightness need): **if you floor/cap the maximum usable exposure time (via
`FrameDurationLimits`, or by picking `ExposureShort`), and the scene is too
dark to reach a correct exposure within that ceiling, the algorithm
compensates by raising `AnalogueGain` instead — which means more sensor
noise in the resulting image, not a rejected/under-exposed frame.** This is
exactly the tradeoff you'd expect: freezing motion at the cost of grain in
low light, never at the cost of exposure accuracy (AE still hits its
brightness target, it just spends gain instead of time to do it). I did not
find an explicit prose sentence to this effect in the manual; this
conclusion is derived directly from reading the tuning table, which is the
actual data the AGC algorithm consumes.

---

## 3. Lifecycle / ordering

### Where each control can go

| Control | `create_still_configuration(controls=...)` / `configure()` | `set_controls()` (pre-`start()`) | `set_controls()` (post-`start()`) |
|---|---|---|---|
| `AfMode`, `AfTrigger`, `LensPosition` | Accepted syntactically (goes into `camera_config["controls"]`), but the examples/tests only ever apply AF controls **after** `start()` — no shipped example configures AF before starting. | Buffered, applied at the first `camera.start(controls)` call (see below). | Normal path — this is how `autofocus_cycle()` and the freeze step work. |
| `ExposureTime`, `AnalogueGain`, `AeEnable`/`ExposureTimeMode`/`AnalogueGainMode` | Yes — `exposure_fixed.py` passes these straight into `create_preview_configuration(controls=...)`. | Same buffering as above; `start_()` specifically inspects these two values to auto-set the new mode controls. | Works, but the automatic Auto/Manual mode derivation shown above only runs inside `start_()` — i.e. it only fires for the *first* `start()`. Changing `ExposureTime` again later via `set_controls()` while the camera is already running does not re-run that derivation, so you may need to set `ExposureTimeMode`/`AnalogueGainMode` explicitly yourself at that point. |
| `FrameDurationLimits` | Yes — both `create_preview_configuration` and `create_still_configuration` already inject a default value for it (`(100, 83333)` for preview, `(100, 1_000_000_000)` for still) merged under whatever you pass. | Buffered same as above. | Normal path. |

Sources for the mechanics: [`picamera2/picamera2.py` — `create_preview_configuration`/`create_still_configuration`/`configure`/`start`/`start_`/`set_controls`](https://github.com/raspberrypi/picamera2/blob/main/picamera2/picamera2.py),
[`picamera2/controls.py`](https://github.com/raspberrypi/picamera2/blob/main/picamera2/controls.py).

### What actually happens at `start()`

```python
def set_controls(self, controls) -> None:
    """Set camera controls. These will be delivered with the next request that gets submitted."""
    self.controls.set_controls(controls)
```

`start()`'s own docstring: "Camera controls may be sent to the camera before
it starts running." Internally, `start_()` reads back everything
accumulated via `configure()`'s `controls=` dict *and* any pre-`start()`
`set_controls()` calls (`self.controls.get_libcamera_controls()`), applies
the `ExposureTimeMode`/`AnalogueGainMode` derivation described above, hands
the whole batch to `self.camera.start(controls)` as libcamera's one-time
"start controls," and only then resets `self.controls = Controls(self)` to
an empty tracker. **Everything set before the first `start()` is therefore
folded into a single up-front control batch; everything set after `start()`
goes through the ordinary per-request `set_controls()` path** (queued with
"the next request that gets submitted").
[`picamera2/picamera2.py`, `start_`/`start`/`set_controls`](https://github.com/raspberrypi/picamera2/blob/main/picamera2/picamera2.py)

### Documented silent no-ops (order-dependent)

All three of these are silent — no exception, the value is just dropped:

- `LensPosition` "is ignored unless `AfMode` is set to `AfModeManual`" —
  set `AfMode: Manual` in the *same* `set_controls()` call (or an earlier
  one already in effect) or the position write does nothing.
- `AfTrigger` "is ignored if `AfMode` is set to `AfModeManual` or
  `AfModeContinuous`" — only fires in `AfModeAuto`.
- `ExposureTime`/`AnalogueGain` "will only take effect if
  `ExposureTimeMode`/`AnalogueGainMode` is Manual. If ... set when [mode] is
  Auto, the value will be ignored and will not be retained." On current
  picamera2 this is handled for you automatically at first `start()` (see
  above) but not on later `set_controls()` calls.

[libcamera `control_ids_core.yaml`](https://github.com/raspberrypi/libcamera/blob/main/src/libcamera/control_ids_core.yaml)

### Settling delay before a capture is valid

`set_controls()`'s own docstring is explicit that a change is "delivered
with the **next** request that gets submitted" — singular, one request
ahead — but libcamera/picamera2 keep more than one request in flight at
once: `create_still_configuration` defaults `buffer_count=1`,
`create_preview_configuration` defaults to `4`, `create_video_configuration`
to `6`
([`picamera2/picamera2.py`](https://github.com/raspberrypi/picamera2/blob/main/picamera2/picamera2.py)).
So a control you set is only guaranteed to be reflected in a request that
was *not already queued* when you called `set_controls()` — with more
buffers in flight, more already-stale frames can come back before your
change is visible. I could not find a single documented fixed "N frames"
number to discard; the manual's own guidance (accessed via a third-party
markdown transcription of the PDF, see caveat below) is to synchronise by
reading metadata rather than counting frames:

> "Setting controls after the camera has started ... there will be a delay
> of several frames before the controls take effect ... Capturing metadata
> is a good way to synchronise an application with camera frames."

Practically, for `pi_camera.py`'s still-capture use (`buffer_count=1`,
one request at a time), the safest pattern after freezing focus/exposure is
to pull and discard (or just inspect) one `capture_metadata()` before
trusting/using a `capture_file()` result, confirming `AfState`/`LensPosition`
(or `ExposureTime`) in the returned metadata match what was requested, rather
than assuming a fixed number of frames.

---

## Recommended code shape for `pi_camera.py`

This only shows the *shape* — every numeric threshold (`AfMode` choice,
frame-duration ceiling, exposure mode) is a placeholder for the follow-up
tuning ticket to fill in.

```python
# raspberry_pi_code/camera/pi_camera.py

async def __aenter__(self) -> "PiCamera":
    try:
        from picamera2 import Picamera2
        from libcamera import controls

        self._cam = Picamera2()
        cfg = self._cam.create_still_configuration(
            main={"size": (self._width, self._height)},
            # FrameDurationLimits caps the slowest shutter AE is allowed to pick,
            # while leaving AE (exposure + gain) running — see research doc §2.
            # controls={"FrameDurationLimits": (MIN_FRAME_US, MAX_FRAME_US)},
        )
        self._cam.configure(cfg)
        self._cam.start()

        await self._lock_focus()
        logger.info("Camera started at %dx%d", self._width, self._height)
    except ImportError:
        logger.warning("picamera2 not available — captures will produce dummy images")
    return self

async def _lock_focus(self) -> None:
    """Run one autofocus scan, then freeze the lens so it can never hunt again.

    No-ops (logs and returns) on hardware with no focus motor.
    """
    if self._cam is None or "AfMode" not in self._cam.camera_controls:
        return

    from libcamera import controls

    def _run() -> tuple[bool, float]:
        focused = self._cam.autofocus_cycle()  # blocks; sets AfMode=Auto internally
        lens_position = self._cam.capture_metadata()["LensPosition"]
        # Freeze regardless of outcome: Manual mode is the only state that
        # guarantees the lens "will never move spontaneously" (libcamera spec).
        self._cam.set_controls({
            "AfMode": controls.AfModeEnum.Manual,
            "LensPosition": lens_position,
        })
        return focused, lens_position

    focused, lens_position = await asyncio.get_running_loop().run_in_executor(None, _run)
    if not focused:
        logger.warning(
            "Autofocus did not converge (AfState != Focused); frozen anyway at "
            "LensPosition=%.3f dioptres", lens_position,
        )
    else:
        logger.info("Autofocus locked at LensPosition=%.3f dioptres", lens_position)
```

Notes tying this back to the findings above:

- `_lock_focus()` runs **after** `self._cam.start()`, matching every shipped
  AF example — `autofocus_cycle()` needs a running camera.
- It guards on `"AfMode" not in self._cam.camera_controls` so it is a no-op
  on modules without a focus motor, and inert in the existing
  `ImportError` dummy-image fallback path.
- It always ends in `AfModeManual` with an explicit `LensPosition`, even on
  AF failure, rather than leaving the camera in `AfModeAuto` — the strictly
  stronger "never move spontaneously" guarantee from the spec.
- The blocking `autofocus_cycle()`/`capture_metadata()` pair is pushed
  through `run_in_executor`, consistent with how `capture()` already
  shells `capture_file()` off the event loop.
- A shutter floor (`FrameDurationLimits`) is shown as a `configure()`-time
  control comment, per §2 — it can also be set later via `set_controls()`
  if the test wants to change it without reconfiguring, since it isn't an
  AF control gated by mode like `LensPosition`/`ExposureTime` are.
- If the tuning ticket instead wants full manual exposure, add
  `"ExposureTime": ..., "AnalogueGain": ...` to the same `configure()`
  controls dict — current picamera2 will derive
  `ExposureTimeMode`/`AnalogueGainMode` = Manual automatically at the first
  `start()` (§2), no `AeEnable` needed.

---

## Open uncertainties

- **What `pi_camera.py` actually experiences today on real hardware is not
  fully nailed down.** I traced the libcamera/IMX708 source default to
  `AfModeManual` @ 1.0 dioptre — not continuous scanning — with no override
  found in the pipeline handler. The one explicit "defaults to continuous
  AF" behaviour I found in the primary sources belongs to rpicam-apps, a
  separate binary this codebase doesn't use. I could not verify on physical
  Pi 5 + Camera Module 3 hardware whether some other layer (a specific
  picamera2/libcamera package version, a Raspberry Pi OS camera default)
  produces the hunting the ticket describes — I only read source code, I
  did not run it on the device. The fix (pin `AfMode` explicitly) is correct
  regardless of which default turns out to be true.
- **Version dependency on the `ExposureTimeMode`/`AnalogueGainMode` split.**
  These controls, and the automatic derivation in `Picamera2.start_()`,
  landed via libcamera patch series submitted through 2025. I read them off
  the picamera2 `main` branch and the latest tagged release (`v0.3.36`,
  2026-05-06); I did not check which exact `libcamera`/`picamera2` package
  version is actually installed on this project's Pi 5 image. On an older
  install, the classic `AeEnable: False` + `ExposureTime`/`AnalogueGain`
  path is the safe fallback (also confirmed working in `exposure_fixed.py`,
  which predates the mode split and never sets `AeEnable`/mode controls
  itself). Worth a `pip show picamera2` / `dpkg -l | grep libcamera` check
  on the actual hardware before the tuning ticket picks an approach.
- **No documented fixed "discard N frames" number.** The manual's own
  guidance is qualitative ("several frames," "capture metadata to
  synchronise"), not a specific count. I derived the mechanism (one request
  ahead per `set_controls()` docstring, bounded by `buffer_count`) from
  source rather than finding an explicit spec'd number.
- **The Picamera2 manual PDF itself resisted direct text extraction in this
  environment** (no `poppler-utils`/`pdftoppm` installed, and a raw fetch of
  the PDF returned unparsed binary structure). The quotes attributed to the
  manual above (the `autofocus_cycle()` recommendation, the "several frames"
  settling-delay guidance) were read via a third-party Markdown
  transcription of the official PDF and then cross-checked against the
  actual picamera2 source/test suite, which corroborates them independently
  — but I did not personally verify the exact wording/section numbers
  against the official PDF byte-for-byte. If precision on the manual's exact
  phrasing matters later, re-fetch
  `https://datasheets.raspberrypi.com/camera/picamera2-manual.pdf` on a
  machine with PDF text extraction available.
- **The gain/noise-under-floored-shutter conclusion (§2) is inferred from
  the AGC tuning table**, not from an explicit prose statement in any
  document — the tuning JSON is genuinely primary (it's the data the
  algorithm runs on), but I did not find the algorithm's C++ implementation
  itself explaining its shutter-vs-gain traversal order in comments, only
  data that's consistent with a "shutter first, then gain" story.

---

## Sources

- [libcamera `control_ids_core.yaml`](https://github.com/raspberrypi/libcamera/blob/main/src/libcamera/control_ids_core.yaml) — `AfMode`, `AfTrigger`, `AfState`, `AfPauseState`, `LensPosition`, `ExposureTime`, `AeEnable`, `AeConstraintMode`, `AnalogueGain`, `FrameDurationLimits`, `ExposureTimeMode`, `AnalogueGainMode`, `AeExposureMode` definitions.
- [`picamera2/picamera2.py`](https://github.com/raspberrypi/picamera2/blob/main/picamera2/picamera2.py) — `create_preview_configuration`, `create_still_configuration`, `configure`, `start`, `start_`, `set_controls`, `autofocus_cycle`.
- [`picamera2/controls.py`](https://github.com/raspberrypi/picamera2/blob/main/picamera2/controls.py) — `Controls` class (`set_controls`, `get_libcamera_controls`).
- [`picamera2/examples/exposure_fixed.py`](https://github.com/raspberrypi/picamera2/blob/main/examples/exposure_fixed.py)
- [`picamera2/tests/autofocus_test.py`](https://github.com/raspberrypi/picamera2/blob/main/tests/autofocus_test.py)
- [`picamera2/apps/app_capture_af.py`](https://github.com/raspberrypi/picamera2/blob/main/apps/app_capture_af.py)
- [`picamera2` CHANGELOG.md](https://github.com/raspberrypi/picamera2/blob/main/CHANGELOG.md) and [releases](https://github.com/raspberrypi/picamera2/releases) (latest at research time: `v0.3.36`, 2026-05-06)
- [libcamera `src/ipa/rpi/controller/rpi/af.cpp`](https://github.com/raspberrypi/libcamera/blob/main/src/ipa/rpi/controller/rpi/af.cpp) — default `AfMode` (line 178).
- [libcamera `src/ipa/rpi/common/ipa_base.cpp`](https://github.com/raspberrypi/libcamera/blob/main/src/ipa/rpi/common/ipa_base.cpp) — `AfMode` control registration/table.
- [libcamera `src/ipa/rpi/pisp/data/imx708.json`](https://github.com/raspberrypi/libcamera/blob/main/src/ipa/rpi/pisp/data/imx708.json) — Pi 5 IMX708 tuning: `rpi.af` ranges/defaults, `rpi.agc` `exposure_modes` shutter/gain tables.
- [Picamera2 manual (PDF)](https://datasheets.raspberrypi.com/camera/picamera2-manual.pdf) — `autofocus_cycle()` recommendation, settling-delay guidance (accessed via third-party Markdown transcription; see Open Uncertainties).
- [raspberrypi/documentation — `rpicam_options_common.adoc`](https://github.com/raspberrypi/documentation/blob/master/documentation/asciidoc/computers/camera/rpicam_options_common.adoc) — `--autofocus-mode` default, `--shutter` behaviour.
- libcamera patchwork — AE control reorganisation history: [patch 15179](https://patchwork.libcamera.org/patch/15179/), [patch 22556](https://patchwork.libcamera.org/patch/22556/).
