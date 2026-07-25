# Peck Deck — Outdoor Deployment Guide

**Site:** Spokane, WA (47.6 °N) · **Mounting:** freestanding yard pole + house/eave
**Power baseline:** Ring battery pack · **Build preference:** off-the-shelf parts
**Status:** planning doc for FLEDGE Phase 4 field bring-up. Nothing here is built yet.

This is the "what will actually go wrong outside" document. It assumes the bench
work in `HARDWARE_TEST_PLAN.md` is done (camera, Tier 1/2/3, GPIO loopback C3)
and that the open item is **C4 — a real sensor on the header** plus everything
the weather does to it.

---

## 0. The Short Version

Three findings dominate everything else. If you read nothing else, read these.

| # | Finding | Consequence |
|---|---|---|
| 1 | **A Ring battery cannot run a Pi 5.** Not "runs it briefly" — it physically cannot source the current, and it has no usable output port. Even if it could, it's ~22 Wh against a ~4 W load: **under 5 hours.** | The battery plan needs to change before anything goes outside. §2 gives a ladder. |
| 2 | **PIR is the wrong sensor for birds.** Feathers are excellent thermal insulation, and consumer PIR modules are *deliberately* tuned to ignore bird-sized targets. Your `TRIGGER_TYPE` default is `pir`. | Change the default. §4 ranks the alternatives; a perch microswitch wins. |
| 3 | **Your Pi already throttles at idle.** `HARDWARE_TEST_PLAN.md` §1 records 73.6 °C idle and `throttled=0x80000` — *on a bench, in open air, in a climate-controlled room.* | A sealed box in a Spokane July is a thermal failure, not a thermal risk. §3 is not optional. |

Everything below is ordered roughly by how likely it is to end your field trial early.

---

## 1. Site Survey — What Spokane Specifically Does To You

Spokane sits in an unusual band: cold-continental winters *and* hot semi-arid
summers, with wildfire smoke on top. You get to design for both extremes in the
same enclosure.

### 1.1 The numbers

| Parameter | Value | What it breaks |
|---|---|---|
| Jan avg high / low | 33 °F / 21 °F | Li-ion charging (see §2.5), condensation cycling |
| Jul avg high / low | 92 °F / 59 °F | Enclosure interior temp, Pi throttling |
| Record high | **109 °F** (Jun 29, 2021) | Design ceiling — assume it recurs |
| Winter cold snaps | Sub-zero °F nights occur most winters | Battery capacity, LCD/gasket embrittlement |
| Annual snowfall | ~44 in (recent years 26–64 in) | Panel/lens occlusion, load on mounts |
| Annual precip | ~16 in (recent years 11–22 in) | Modest — but it arrives concentrated |
| Diurnal swing (summer) | **~33 °F day-to-night** | This is the condensation driver, not rain |
| Wildfire smoke | Jul–Sep, AQI has exceeded 200 | Image quality, IR beam attenuation, lens fouling |
| Dec solar | ~1–1.5 peak-sun-hours/day | Kills naive solar sizing (§2.6) |

### 1.2 Annual hazard calendar

```
        JAN  FEB  MAR  APR  MAY  JUN  JUL  AUG  SEP  OCT  NOV  DEC
FREEZE  ###  ###  ##.  .            .              .    .##  ###   <- battery charging blocked
SNOW    ###  ##.  ..                                    .    .##   <- lens/panel occlusion
HEAT              .    ..   ###  ###  ###  ##.  .                  <- Pi throttling, enclosure
SMOKE                            ..   ###  ###  ##.                <- image quality collapse
CONDENS ###  ###  ##.  ..   ##.  ###  ###  ###  ##.  ..   ##.  ### <- year-round, always design for it
DAYLIGHT 9h  10h  12h  13h  15h  16h  15h  14h  12h  11h  9h   8h  <- duty-cycle budget (§2.4)

  ### = high    ##. = moderate    ..  = low    (blank) = negligible
```

Two readings worth internalizing:

- **Condensation is the only hazard with no off-season.** Rain is a 16-inch-a-year
  problem here; the 33 °F day/night swing is a 365-day problem. Design for the
  swing and the rain takes care of itself.
- **There is no comfortable window.** Your best months for a *thermal* trial
  (Apr–May, Oct) are your worst for battery duration (short days, cold nights).

### 1.3 Bird season, since it's the actual point

Spokane's feeder traffic peaks Nov–Mar (juncos, chickadees, nuthatches, house
finches, flickers) — which is exactly when your power budget is worst and
condensation is worst. Summer traffic is thinner and more erratic. **Plan the
real deployment for winter and the shakedown for fall.**

---

## 2. Power — The Binding Constraint

### 2.1 Why the Ring battery doesn't work

You asked to start with a Ring pack. Here's the honest accounting, because
"too onerous to swap" turns out to mean *twice a day*, not *twice a month*.

**Capacity.** The Quick Release Battery Pack is 6040 mAh at 3.65 V ≈ **22 Wh**.
The newer Quick Release **Ultra** is 9400 mAh at 3.6 V ≈ **33.8 Wh**.

**Load.** A Pi 5 draws ~3.0 W headless on WiFi, ~3.7 W with the camera streaming,
and up to 8.8 W under full load. Call the working average **4.0 W** with Tier 1
inference bursts and periodic uploads.

```
  22 Wh  /  4.0 W  =  5.5 hours   (at 100% conversion efficiency — impossible)
  22 Wh  /  4.5 W  =  4.9 hours   (with a realistic 88%-efficient boost converter)
```

**So: under five hours.** The Ultra pack gets you to roughly 7.5. A Ring camera
gets months from the same cell because it sleeps at microamps between events and
wakes for a few seconds. A Pi 5 has no equivalent state while it's waiting for a
bird.

**And it's worse than that — the pack has no usable output.** Two hard blockers:

1. **No output port.** The micro-USB port on a Ring pack is a *charge* input. The
   discharge path is a set of proprietary spring contacts sized for the doorbell's
   own connector. There's no supported way to draw from it.
2. **Current ceiling.** A Pi 5 officially wants 5 V @ 5 A (27 W). At the pack's
   3.65 V nominal that's **>7 A** on the input side. A single-cell pack with a
   protection circuit designed for a ~1 A camera load will trip, sag, or refuse.
   You cannot boost your way out of a cell that won't source the current.

You could fabricate contacts and add a boost converter, and you'd have spent a
weekend to earn 4.9 hours of runtime from an unfused lithium cell mounted outside
in a Spokane winter. It isn't a good trade.

**The thing to keep from the Ring idea is the *ergonomics*, not the pack** — a
sealed, swappable, tool-free block you can rotate on a charger. That's achievable;
it just needs 4–10× the energy.

### 2.2 The runtime ladder

Assumes a 4.0 W average load. "Gated" = the dawn/dusk duty cycling in §2.4, which
is close to free and roughly doubles everything.

| Rung | Option | Usable energy | Continuous | Gated (winter) | Verdict |
|---|---|---|---|---|---|
| 0 | Ring Quick Release | 22 Wh | **4.9 h** | ~11 h | Not physically usable. Listed for the math only. |
| 0+ | Ring Ultra | 33.8 Wh | 7.5 h | ~17 h | Same physical blockers. |
| **A** | **USB-C PD power bank, 25,000 mAh (~95 Wh nameplate, ~80 Wh usable at 5 V)** | 80 Wh | **20 h** | **~2 days** | **Start here.** Off-the-shelf, safe, swappable, ~$50. |
| B | 2× rung A on a changeover, or one 40,000 mAh bank | ~150 Wh | 37 h | ~4 days | Swap weekly-ish. Good winter trial config. |
| C | 12 V 20 Ah LiFePO4 + 12→5 V buck (5 A) | 230 Wh | 57 h | **~6 days** | Best off-grid answer. Handles cold far better than Li-ion. |
| D | Rung C + 100 W panel + MPPT, tilted ~65° | — | indefinite Mar–Oct | marginal Dec–Jan | See §2.6 before buying. |
| **E** | **Mains at the eave (24 V DC down the pole, or PoE)** | ∞ | ∞ | ∞ | **The real answer.** See §2.7. |

> **Recommendation:** buy a **rung A** bank this week and run the shakedown on it
> — 20 hours is enough to learn everything about condensation, triggering, optics
> and squirrels. Decide between C, D and E only after the shakedown tells you
> whether the yard pole is even the right location.

### 2.3 Power block diagram (rung A / rung C)

```
  RUNG A — power bank                    RUNG C — LiFePO4
  ===================                    ================

  [ 25,000 mAh USB-C PD bank ]           [ 12 V 20 Ah LiFePO4 ]
   |  must support                        |  BMS w/ LOW-TEMP
   |  "pass-through" OFF                  |  CHARGE CUTOFF  <-- critical, §2.5
   |  and NOT auto-sleep   <-- §2.8       |
   |                                      +--[ 5 A inline fuse ]
   +-- USB-C cable, 5 A rated             |
       (60W+ / e-marked)                  +--[ 12V -> 5V buck, 5 A, e.g. Pololu D36V50F5 ]
   |                                      |     ^ needs >=25 W headroom
   +-- [ Pi 5 USB-C in ]                  |
                                          +-- [ Pi 5 USB-C in ]
   Add: usb_max_current_enable=1
        in /boot/firmware/config.txt      Add a 2200-4700 uF electrolytic across
        (or the Pi caps peripherals       the buck output. The Pi 5's camera+WiFi
        at 600 mA and browns out          current spikes will otherwise trip the
        under camera+WiFi spikes)         converter's OCP on cold mornings.
```

**The single most common failure in Pi outdoor builds is undersized power, and it
does not look like a power problem.** It looks like SD card corruption, random
reboots during capture, and WiFi dropping. If you see those, suspect the supply
before you suspect the code.

### 2.4 Duty cycling — the cheapest 2× you will find

Birds don't feed at night. Your own simulator already encodes this (dawn/dusk
weighted visits in `backend/simulator.py`). Sleeping from dusk to dawn cuts
consumption by 35–65% depending on season, for zero hardware cost.

The Pi 5 has an RTC with a wake alarm, and the EEPROM setting
`POWER_OFF_ON_HALT=1` drops the halted board from **~1.2–1.6 W to ~0.01 W** —
a >100× reduction. Without that setting, "shutting down" a Pi 5 saves you almost
nothing, which surprises people.

```bash
# One-time, on the Pi:
sudo rpi-eeprom-config -e
#   set:  POWER_OFF_ON_HALT=1
#   set:  WAKE_ON_GPIO=0          # otherwise GPIO activity defeats the low-power state

# Then, as the nightly shutdown (systemd timer at civil dusk):
#   wake 30 min before sunrise, then halt into the low-power state
echo 0 | sudo tee /sys/class/rtc/rtc0/wakealarm
date '+%s' -d '05:30 tomorrow' | sudo tee /sys/class/rtc/rtc0/wakealarm
sudo halt
```

Caveats worth knowing before you rely on it:

- The RTC's own retention current is single-digit µA, so **timekeeping survives
  months, not years**, on the coin cell. It also needs the optional RTC battery
  connected, or the alarm is lost on power removal.
- **Boot takes 20–30 s.** This is fine for a scheduled dawn wake. It is *useless*
  as an event-driven wake — a bird will be long gone. Do not design a
  "sensor wakes the Pi" architecture; that's a trail-camera pattern and it does
  not transfer to a 30-second boot.
- Compute sunrise/sunset properly rather than hardcoding — Spokane's day length
  swings from 8 h to 16 h across the year. `python3 -m pip install astral`.

### 2.5 Cold and lithium — the part that destroys batteries

**Li-ion cannot be charged below 0 °C / 32 °F.** Doing so plates metallic lithium
on the anode: permanent capacity loss, and in the bad case an internal short.
This is not a derating, it's damage.

Spokane spends roughly four months where the *daytime high* can sit below
freezing. That means:

- **Solar + Li-ion in a Spokane winter requires a BMS with a low-temperature
  charge cutoff.** Not optional. Buy the pack that advertises it.
- **LiFePO4 is the better chemistry here** — wider temperature range, far safer
  failure mode, and 2000+ cycles. Still needs the low-temp charge cutoff.
- **Discharge is fine when cold**, but capacity drops ~20–30% near freezing. Your
  6-day rung C becomes ~4.5 days in January. Budget for it.
- If you're swapping packs by hand (rung A/B), this all goes away — you charge
  indoors at room temperature. **That's a real, underrated advantage of the
  swappable approach**, and an argument for staying on rung B longer than you'd
  think.

### 2.6 Solar in Spokane — read before buying a panel

Summer solar here is easy. Winter solar is a trap.

```
  Daily energy need (gated):   summer 15 h x 4 W = 60 Wh
                               winter  9 h x 4 W = 36 Wh

  50 W panel, summer:  50 W x 5.0 PSH x 0.7 derate = 175 Wh/day   -> 3x margin, fine
  50 W panel, winter:  50 W x 1.2 PSH x 0.6 derate =  36 Wh/day   -> EXACTLY break-even
                                                                     i.e. one cloudy
                                                                     day and you're dark
```

So: **a 50 W panel that looks generous in July is break-even in December, before
you account for snow.** And a snow-covered panel produces zero.

If you go solar:

- **Size for December, not July.** 100 W minimum.
- **Tilt steeply — 60–70°.** Spokane is 47.6 °N; winter-optimal tilt is roughly
  latitude + 15 ≈ 63°. Near-vertical also *sheds snow*, which matters more than
  the angle optimization does.
- Face true south, and check the winter sun path — the sun barely clears 19°
  above the horizon at noon in late December. A fence or shed that's irrelevant
  in June will shade you completely in December.
- Budget 3 days of autonomy in the battery, because overcast + snow cover
  regularly stacks.

### 2.7 The option you should seriously consider

You said the eave is a candidate mounting point. **If the eave is viable, power
becomes a solved problem and so does WiFi.** Two clean off-the-shelf routes:

- **PoE.** Outdoor-rated Cat6 from the house to a PoE splitter at the feeder
  (802.3at gives 25 W — enough headroom). Cleanest single-cable answer: power and
  network in one run, and it gets the Pi off WiFi entirely.
- **Low-voltage DC.** A 24 V supply indoors, 16/2 outdoor landscape wire out to
  the pole, buck to 5 V at the enclosure. Cheap, and 24 V tolerates voltage drop
  over a long run far better than 5 V does (never run 5 V more than a few feet).

The reason this deserves a hard look: **every other section of this document
gets easier with mains power.** You can afford active cooling, an enclosure
heater, always-on operation, and Tier 2 offload. The PRD's "runs entirely from
battery, no external power at the feeder" is a legitimate design goal — but it's
worth confirming it's still a goal you want, rather than one inherited from an
early draft. If it is, rung C/D is the answer and this section is moot.

### 2.8 Power bank gotcha (rung A)

Most USB power banks **auto-shut-off below a minimum load** — typically 50–100 mA
— to save their own charge. A Pi 5 in a low-power idle can drop under that
threshold and the bank will simply switch off. Symptoms: the feeder dies
overnight, seemingly at random.

Fixes, in order of preference: buy a bank explicitly advertising **"always-on"
/ "low-current mode"** (common on banks aimed at trail cameras and IoT); or use
a bank with **pass-through charging** and leave a trickle load; or, crudely, park
a 100 Ω resistor across the rail to keep 50 mA flowing (wasteful — 0.25 W — but
it works).

---

## 3. Enclosure & Thermal

### 3.1 Start from your own throttling data

`HARDWARE_TEST_PLAN.md` §1 records the Pi at **73.6 °C idle** with
`throttled=0x80000` set — meaning the soft temperature limit *has already been
hit* — on a bench, in open air, at room temperature.

Now do the arithmetic for a sealed box:

```
   Spokane July ambient, in shade .................  95 F  = 35 C
   + solar gain, light-coloured sealed box ........  +15 C  (a dark box: +30 C)
   = enclosure interior air .......................        = 50 C
   + Pi SoC rise over local air, passive, 4 W .....  +25 C
   = SoC temperature ..............................        = 75 C   <-- already at your
                                                                        bench idle temp,
                                                                        before inference

   Pi 5 soft-throttles at 80 C, hard-throttles at 85 C.
```

You have essentially **no thermal margin**. Tier 1 inference bursts will cross it.
This is the second-most-likely thing to end your trial, after power.

### 3.2 Thermal mitigations, ranked by effect per dollar

1. **Mount in shade, and use a separate sunshade.** A detached shade board or a
   second "roof" standing off the enclosure by 1–2 inches, with air gapping
   between, blocks direct gain while letting the enclosure radiate. This is worth
   more than everything else combined and costs almost nothing. Radiant load is
   the dominant term, not ambient.
2. **Light-coloured enclosure.** White or light grey. A black box in Spokane sun
   is a solar oven — that's the difference between +15 °C and +30 °C above.
3. **Conduct heat *out* through the wall.** Bolt the Pi's heatsink to an aluminium
   plate, and bolt that plate to the enclosure wall with thermal pad between.
   Now the whole box is your heatsink. In a sealed enclosure, conduction to the
   wall is the only path out — internal fans just stir warm air.
4. **Keep the Pi 5 active cooler**, even sealed. Circulating internal air still
   gets heat from the SoC to the walls. It costs ~0.4 W.
5. **Underclock.** `arm_freq=1800` in `/boot/firmware/config.txt` cuts peak power
   meaningfully. Your Tier 1 inference is 57.9 ms — you can afford 80 ms.
6. **Don't run Tier 2 when hot.** Every Tier 2 call transmits a full JPEG over
   WiFi; the radio is a real thermal and power contributor. `TIER_PREFERENCE=local`
   during heat events. Your measured Tier 1 accuracy (20/20 top-1) makes this a
   cheap call.

### 3.3 Condensation — the failure that looks like nothing else

A sealed box is not a dry box. It's a box with a fixed amount of humid air. The
33 °F diurnal swing means that air crosses its dew point every single night, and
water condenses on the coldest surface — which will be your camera window, then
the PCB.

```
   DAY                          NIGHT
   ---                          -----
   Interior 50 C, RH 20%        Interior 5 C, RH 100%
   air holds lots of water  ->  air holds almost none  ->  the difference
                                                            lands on your lens
                                                            and your board
```

The fix is three things together, not any one of them:

- **A pressure-equalisation vent** (Gore PolyVent, Bud PMF series, or any
  IP-rated breather membrane, ~$8). It passes water *vapour* while blocking
  liquid water and dust. **A truly sealed box is worse than a vented one** — it
  pumps moist air in through every gasket imperfection as it heats and cools, and
  never lets it out. This part is counter-intuitive and it's why people who
  "sealed it really well" have the worst condensation.
- **Desiccant.** Rechargeable silica gel packs with a colour indicator, ~50 g.
  Bake them in the oven when they turn. Check monthly at first.
- **Orientation and drainage.** Mount so that any water that does form runs
  *away* from the board, and put a **drip loop** in every cable so water tracks
  down the cable and drips off *below* the gland instead of running into it.

### 3.4 Off-the-shelf enclosure options

You said off-the-shelf, so:

| Option | Pros | Cons | Notes |
|---|---|---|---|
| **Sixfab Outdoor IP65 Project Enclosure** (~$40) | Purpose-built for Pi, clear polycarbonate lid, gasket, mounting ears, four grommets included, standoffs for any Pi | Clear lid = greenhouse effect; small for a battery | **Best starting point.** Add an external sunshade and it's fine. Clear lid also lets the camera shoot through the lid itself. |
| **Generic "Raspberry Pi IP65 Weatherproof IoT Enclosure"** (~$25) | Cheap, same idea | Fit and gasket quality varies | Fine for a first trial you expect to modify |
| **Hammond 1554/1555 series with gasket** | Genuinely industrial, huge size range, UV-stable options | You drill everything yourself, no Pi standoffs | Pick a light grey. Good if you want room for a rung-C battery in the same box. |
| **Electrical junction box (PVC, from a hardware store)** | $10, enormous, weatherproof by design, available locally today | Opaque (needs a camera port), no internal mounting | Genuinely underrated. Grey PVC is UV-stable and light-coloured. |

**Sizing:** leave 2× the volume you think you need. Thermal headroom scales with
surface area, and you *will* want to add the battery, a buck converter, and a
sensor bracket you haven't designed yet.

### 3.5 Enclosure layout

Face view, showing where things go and — more importantly — where they don't:

```
        +=========================================+
        |  [ external sunshade stands off 1-2"  ] |   <- detached, air gap behind
        +=========================================+
        |                                         |
        |   +-----------+                         |
        |   |  CAMERA   |   <- lens against the window, hooded (see 5.2)
        |   |  PORT     |                         |
        |   +-----------+                         |
        |                                         |
        |   [ Pi 5 + active cooler ]              |
        |     bolted to Al plate ->  ###########  |   <- thermal path to wall
        |                                         |
        |   [ battery ]      [ buck / fuse ]      |
        |                                         |
        |   [ desiccant pack ]                    |
        |                                         |
        +--(o)-----------(o)-----------(o)--------+
            |             |             |
          VENT        SENSOR GLAND   POWER GLAND
        (breather)    (trigger wire)  (or PoE)
         ON A SIDE     ON THE BOTTOM   ON THE BOTTOM
         WALL, NOT     FACE            FACE
         THE TOP

        Rules:
          - ALL penetrations on the BOTTOM or a SIDE face. Never the top.
            Water finds the top ones. Every time.
          - Every cable gets a DRIP LOOP below its gland.
          - Unused gland holes get blanking plugs, not tape.
```

Cable glands: buy a variety pack of **PG7 / PG9 nylon glands** (~$10 for 20).
Match the gland's clamping range to the actual cable diameter — an oversized
gland on a thin cable does not seal, which is the most common leak in amateur
builds.

---

## 4. Triggering — Where Your Current Default Is Wrong

Your `config.py` defaults to `TRIGGER_TYPE=pir` on BCM17 with
`DEBOUNCE_SECONDS=30`. The debounce is well chosen. The sensor is not.

### 4.1 Why PIR fails on birds

PIR detects *moving thermal contrast*. Birds defeat it twice over:

- **Feathers are outstanding insulators.** A bird's core is 104–107 °F, but its
  *surface* — which is all a PIR sees — is close to ambient. That's the entire
  evolutionary point of plumage.
- **Consumer PIR modules filter small targets deliberately.** Security PIRs
  advertise "no false alarms from birds and small animals" as a *feature*. You'd
  be fighting the sensor's designed behaviour.
- **Summer makes it worse.** As ambient rises toward the bird's apparent surface
  temperature, contrast — and therefore detection — collapses. Your July
  performance will be worse than your January performance, on top of everything
  else July does to you.

Field reports are consistent: intermittent detection, larger birds more reliable
than small ones, and finch-sized targets only within ~3–6 m under good contrast.
For a feeder camera that's a miss rate you'd never accept.

### 4.2 The options, ranked

| Rank | Trigger | Reliability | Cost | Works with your code? |
|---|---|---|---|---|
| **1** | **Perch microswitch / lever switch** | Excellent | ~$5 | Yes — falling edge, pull-up. Wire it as `ir_beam`. |
| 2 | **Modulated IR beam break (38 kHz)** | Good | ~$10 | Yes — that's the `ir_beam` class, as designed. |
| 3 | Software motion detection on the camera | Good | $0 | No — needs new code, and burns power continuously |
| 4 | Microwave doppler (RCWL-0516) | Poor | ~$3 | Triggers on branches, rain, and passing cars |
| 5 | PIR | Poor for birds | ~$3 | Yes, but see §4.1 |

### 4.3 Recommended: the perch switch

A hinged perch resting on a lever microswitch. A bird lands, the perch deflects
a millimetre, the switch closes.

```
        SIDE VIEW

            bird lands here
                 |
                 v
        ========================   <- perch dowel, hinged at the left
        ^                     |
       hinge            small deflection (~1 mm)
                              |
                              v
                        [ o ]  <- lever microswitch (SPDT, "roller lever" type)
                         | |
                         | +---- GND
                         +------ BCM 17 (internal pull-up)

        A bird's weight closes the switch -> pin goes LOW -> FALLING edge
        -> which is exactly what IRBeamTrigger already listens for.

        Tune with the lever arm length and a light return spring so that:
          - a 10 g chickadee triggers it
          - wind alone does not
          - a 500 g squirrel also triggers it (that's fine! see 6.4)
```

Why this wins for your build:

- **Immune to everything Spokane does.** Sun angle, wildfire smoke, snow, ambient
  temperature — none of it affects a mechanical switch.
- **It self-selects for the shot you actually want.** It fires when a bird is
  *perched at a known position*, which means a known focus distance and a known
  framing. That's a large, free accuracy win for Tier 1 — you're no longer
  classifying birds at random distances and angles.
- **Zero standby power.** An IR beam emitter draws current continuously; a switch
  draws none. On a battery budget this is not a rounding error.
- **No code change.** It's a falling edge into a pull-up. `IRBeamTrigger` already
  configures `PUD_UP` + `GPIO.FALLING` with `bouncetime=200`. Wire it up, set
  `TRIGGER_TYPE=ir_beam`, done. Your C3 loopback test already proved that path.

The trade-off, stated plainly: **you only catch birds that land on the perch.**
Hovering birds, ground feeders, and anything on the far side of the feeder are
invisible. For a feeder-cam that's an acceptable and arguably desirable filter,
but it's a real limitation and you should decide on it consciously.

**Parts:** any SPDT lever microswitch (Omron D2F-01L or a generic "KW11-3Z" pack,
~$8 for 10). Get the version with a roller lever. Seal the switch body itself —
they are not weatherproof — with a dab of silicone at the wire entry, or buy a
sealed IP67 version.

### 4.4 If you go with the IR beam instead

One piece of advice matters more than all the rest: **use a modulated 38 kHz
receiver, not a bare photodiode or phototransistor.**

A bare IR receiver in an outdoor setting is saturated by sunlight — the sun is a
massive broadband IR source, and a low sun angle pointed straight into your
receiver will blind it completely. Spokane's winter sun sits at ~19° above the
horizon at noon; it *will* find your receiver.

A modulated receiver (TSSP4038, or TSOP4838) only responds to IR pulsed at 38 kHz
and rejects everything else, including sunlight and incandescent flicker.

```
        TOP VIEW, across the feeding port

        [ IR LED ]- - - - - - - - - - - ->[ TSSP4038 ]
         940 nm                            active LOW
         pulsed at 38 kHz                  output
         (555 timer or a Pi PWM pin)
             |<------ 4 to 6 inches ------>|
                (short baseline = strong signal
                 = tolerant of fog, smoke, dust)

        Both ends on ONE rigid bracket. If they can move
        independently, thermal expansion will misalign them
        across a 33 F daily swing.

        Output is active-LOW -> beam broken pulls the pin LOW
        -> FALLING edge -> matches IRBeamTrigger exactly.
```

**Software guard you'll need either way:** snow, a leaf, a spider web, or ash
fallout can block the beam *persistently*. That looks like a trigger, then
silence — or, worse, a trigger storm. Add a fault check: if the beam reads
blocked continuously for more than ~60 s, log a device fault and suppress
captures until it clears. There's no such guard in `IRBeamTrigger` today, and
this is the sensor's main failure mode outdoors.

### 4.5 Debounce and trigger storms

`DEBOUNCE_SECONDS=30` is a good default for the perch switch. Two things to watch
once you're live:

- **Starlings and house sparrows arrive in flocks** and will occupy the perch
  continuously. With a 30 s debounce that's 120 captures/hour, all of the same
  species, filling your offline queue (`MAX_QUEUED_SIGHTINGS=200`) in under two
  hours if the network is down.
- Consider a **per-species adaptive debounce** later — if the last N captures
  were all the same species at high confidence, back off. That's a nice Phase 9
  feature and not something to build before the field trial.

---

## 5. Camera & Optics

### 5.1 Point the camera north

Free, permanent, and it beats any amount of post-processing.

```
                    N
                    ^
                    |
              [ CAMERA looks this way ]
                    |
              [ feeder / perch ]
                    |
        W  <---  [ SUN'S PATH ]  --->  E
                    |
                    S              <- sun is always BEHIND the camera
                                      -> subject is front-lit all day
                                      -> no lens flare, no silhouettes,
                                         no blown highlights
```

A south-facing camera silhouettes every bird against the sun for half the day and
your classifier confidence will show it. In Spokane's low winter sun this is the
difference between usable and useless morning captures.

### 5.2 Shooting through the window

```
        CROSS-SECTION of the camera port

          outside                     inside
             |                           |
        =====+===========================+=====   <- enclosure wall
             |                           |
        [hood]|  [ clear window ]  |     |
        ------+--##################--+---+
              |  ^                   |
              |  |                   |
              |  lens sits AGAINST   |
              |  the window, with a  |
              |  black foam/felt     |
              |  ring as a light     |
              |  seal                |
              |                      |
              +---- [ IMX708 ] ------+

        Two rules:
        1. NO AIR GAP between the lens and the window, and no stray light
           reaching the inside of the window. Any gap = internal reflections
           = a permanent haze over every image. The black ring is what fixes it.
        2. The HOOD is a rain shield AND a lens shade. Extend it 1-2 inches
           past the glass, angled down. It keeps rain off the window and
           low sun out of the lens.
```

If you use the Sixfab enclosure, the clear polycarbonate lid *is* your window —
just add the light seal and an external hood. If you use an opaque box, an
off-the-shelf option is a **acrylic sight glass / inspection window** or simply a
disc of 2 mm acrylic bedded in clear silicone from the inside.

**Polycarbonate vs acrylic vs glass:** acrylic has better optical clarity and UV
stability; polycarbonate is tougher but yellows and scratches more easily —
relevant when squirrels are involved (§6). Glass is optically best and won't
scratch, but cracks. For a feeder that squirrels will physically contact, **glass
in a recessed, protected port** is the durable answer.

### 5.3 Lock the focus — a real code gap

`raspberry_pi_code/camera/pi_camera.py:28` builds a still configuration and
starts the camera with **no autofocus configuration at all**, so the IMX708 runs
in its default AF mode. Outdoors that means the lens hunts — on a moving branch,
on falling snow, on the window itself — and a bird that's present for 2 seconds
gets a capture mid-hunt.

Since the perch switch (§4.3) fixes the subject at a known distance, **lock the
focus manually**:

```python
# in PiCamera.__aenter__, after configure() and before/after start()
self._cam.set_controls({
    "AfMode": 0,              # 0 = Manual
    "LensPosition": 1 / 0.30, # dioptres: 1/distance_in_metres. 0.30 m -> 3.33
})
```

Measure the perch-to-lens distance once, convert to dioptres, done. Recommended
geometry: **10–16 inches (0.25–0.40 m)** from lens to perch. That's comfortably
within the Module 3's ~10 cm minimum focus, and it makes a sparrow fill a useful
fraction of the 1920×1080 frame.

Two related controls worth setting at the same time, both for the same reason
(the camera has one job, on a known subject, and shouldn't be guessing):

- **A shutter-speed floor.** Birds move fast; anything slower than ~1/500 s
  smears a chickadee. Cap exposure time and let gain rise —
  a noisy sharp frame classifies far better than a clean blurry one.
- **Exposure metering on the centre.** Snow in the frame will fool an
  average-metered exposure into underexposing the bird by a stop or more, and
  Spokane has snow on the ground for about half of winter.

### 5.4 Wildfire smoke and image quality

Aug–Sep smoke is a genuine, Spokane-specific accuracy hazard: it flattens
contrast and throws a strong orange cast over everything. Your Tier 1 model was
measured at 20/20 top-1 on clean images; expect measurable degradation on heavy
smoke days, and expect it to be *systematic* rather than random.

Two cheap responses:

- **Log it.** You already store per-sighting confidence. During smoke season the
  confidence distribution shifting downward is a signal worth having, and it's
  the kind of thing that's obvious in hindsight and invisible if you didn't
  record it.
- **Clean the window weekly during smoke season.** Ash deposits, and a hazy
  window is indistinguishable from hazy air to the classifier.

---

## 6. Squirrels & Other Wildlife

Squirrels are not a nuisance for this build — they're the **single most likely
cause of physical destruction**, because unlike a normal feeder you have cables
and optics out there.

### 6.1 Baffle geometry (yard pole)

The numbers are well established and worth following exactly:

```
                 [ FEEDER + ENCLOSURE ]
                        |
                        |   >= 16 inches   <- squirrel can reach over
                        |                     a shorter gap
                 -------+-------
                /               \
               /   WRAP-AROUND   \        <- baffle, min 15" diameter
              /      BAFFLE       \          (torpedo or stovepipe also fine)
             +---------------------+
                        |
                        |
                        |   baffle TOP >= 4-5 ft above ground
                        |   (a squirrel jumps ~4 ft vertically
                        |    from a standing start)
                        |
                        |
        ~~~~~~~~~~~~~~~~+~~~~~~~~~~~~~~~~
              ground    |
                        |   pole set >= 18-24" deep,
                        |   concrete if you can

        HORIZONTAL CLEARANCE (plan view):

              tree                fence               deck rail
               |                    |                    |
               +--- >= 10 ft -------+--- >= 10 ft -------+
                            \       |       /
                             \      |      /
                              [ FEEDER POLE ]

        A squirrel jumps ~8 ft horizontally, and downward from a height
        much further. 8 ft is the common advice; 10-12 ft is the advice
        from people who've lost the argument once.
```

**Pole choice:** smooth 1-inch steel or aluminium, not wood and not anything
with a textured coating. A 4×4 wooden post is a ladder.

### 6.2 The eave mount changes the threat model

An eave/soffit mount removes the climbing route entirely — but introduces a
*drop-in* route from the roof, which baffles cannot address. Squirrels will
happily descend a wall or drop from a gutter. If you mount at the eave, you're
relying on:

- Distance from the roof edge and any gutter (a squirrel can drop several feet
  onto a target it can see).
- A **dome baffle above** the unit rather than below it.
- Physical inaccessibility of the enclosure itself, which is the real goal.

### 6.3 Protect the cables — this is the actual risk

Squirrels chew constantly; it's dental maintenance, not appetite. A chewed USB-C
power cable at 5 A is a fire risk, and a chewed sensor lead is a mystery
debugging session.

- **Run every cable inside the pole** if you can, or inside **flexible metal
  conduit** (armoured "BX"/greenfield, ~$1/ft). Split loom plastic is *not*
  enough — they chew straight through it.
- **No exposed connectors.** Everything terminates inside the enclosure.
- Keep runs short and under tension; a slack loop is an invitation.

### 6.4 Other Spokane wildlife

| Animal | Risk | Mitigation |
|---|---|---|
| **Squirrels** (western gray, fox, red) | Cable chewing, lens scratching, sitting on the camera, dislodging the unit | §6.1–6.3 |
| **Raccoons** | Genuinely dexterous — will open latches and unplug things. Nocturnal. | Latching or screwed-shut enclosure. Nightly shutdown (§2.4) means you won't even see them. |
| **Deer** | Common in Spokane neighbourhoods; will knock a pole over reaching for seed | Deep-set pole, height. Note that feeding deer is discouraged by WDFW and restricted in some areas. |
| **Black bear** | Rare but real on Spokane's urban fringe | If bears are ever reported nearby, take the feeder in at night. A bear ends this project in one visit. |
| **Starlings / magpies / house sparrows** | Not destructive, but will monopolise the feeder and flood your sighting queue | §4.5, and seed selection (safflower and nyjer deter starlings and squirrels; they don't like it, finches do) |

**A note on the perch switch and heavy animals:** a squirrel triggering it is
*fine* and arguably useful — you get a photo, Tier 1 classifies it as
`background` or low-confidence, and you have a squirrel-visit log. Don't
over-engineer a weight threshold. Do make sure the perch and switch survive a
500 g animal sitting on them, which a lever microswitch will as long as there's
a hard stop limiting the deflection.

---

## 7. Network

### 7.1 The yard pole is the problem case

The eave mount will be fine. A pole in the middle of the yard, behind an exterior
wall, at ground level, is where WiFi goes to die — and your architecture depends
on it for Tier 2 offload *and* sighting upload.

- **Use 2.4 GHz, not 5 GHz.** Roughly double the range through walls and
  foliage. The Pi 5 will happily prefer 5 GHz if you let it; lock the band.
- **Survey before you dig.** Put the Pi at the exact proposed location, on
  battery, and log RSSI for a full day:
  ```bash
  while true; do echo "$(date +%T) $(iwconfig wlan0 2>/dev/null | grep -o 'Signal level=.*')"; sleep 60; done
  ```
  **Target better than −70 dBm.** Worse than −80 dBm and you'll see intermittent
  upload failures that look like backend bugs. Note that summer foliage will cost
  you 5–10 dB versus a bare-branch winter survey — survey in the worse season or
  add margin.
- **Wet snow on the enclosure attenuates 2.4 GHz noticeably.** If you're marginal
  in October you'll be offline in January.
- If it's marginal: an outdoor mesh node or a directional panel antenna at the
  house pointed at the feeder. Or revisit §2.7 and run PoE, which solves power
  and network in one trench.

### 7.2 Config that will bite you

- **`BACKEND_URL` and `INFERENCE_SERVER_URL` are hardcoded LAN IPs**
  (`192.168.1.100`). A DHCP lease change on the gaming PC silently takes the
  feeder offline. **Set a DHCP reservation** for the PC, and give the Pi one too
  so you can always find it.
- **The gaming PC is the backend.** It reboots, sleeps, and gets Windows updates.
  Every one of those is an outage the Pi has to ride out on its offline queue.
  Make sure the Docker stack has a restart policy and the PC doesn't sleep.
- **`MAX_QUEUED_SIGHTINGS=200`** at ~300 KB/JPEG is ~60 MB — fine for the SD card.
  But at a busy feeder that's a few days, not a few weeks. If you expect long
  outages, raise it *and* confirm the SD card has room.
- **Set `TIER_PREFERENCE=local`** for the field trial. It halves radio-on time
  (Tier 2 sends the full image to the inference server *and then* the sighting to
  the backend), which is both a power and a thermal saving. Your Tier 1 accuracy
  is measured at 20/20 top-1; you're not giving much up.

### 7.3 SD card longevity

Unplanned power loss corrupts SD cards, and a battery-powered feeder has
unplanned power loss as a *design feature*. Before it goes outside:

- Move logs to `tmpfs` (`/var/log` in RAM) via `log2ram` or an fstab entry.
- Set `commit=600` on the root filesystem mount to batch writes.
- Consider booting from a **USB SSD** instead — the Pi 5 supports it, and it
  removes the single most common long-term failure mode of outdoor Pi installs.
- **Take an image of the working SD card** before deployment. When it does
  corrupt, you want a 10-minute recovery, not a rebuild.

---

## 8. Mounting Layouts

### 8.1 Yard pole

```
                        ___________
                       /  sunshade \          <- detached, 1-2" standoff
                      +=============+
                      |             |
                      |  ENCLOSURE  |         <- camera looks NORTH,
                      |    [O]--->  |            downward ~10 degrees
                      |             |
                      +==+=======+==+
                         |       |
                    +----+       +----+
                    |    PERCH + FEED  |      <- 10-16" from lens
                    |       [=======]  |         perch switch here
                    +------------------+
                              |
                              |    >= 16"
                     ---------+---------
                    /                   \
                   /   BAFFLE (>=15" D)   \
                  +-----------------------+
                              |
                              |   top of baffle
                              |   >= 4-5 ft
                              |
                              |   <- cable inside the pole
                              |      or in metal conduit
                              |
        ~~~~~~~~~~~~~~~~~~~~~~+~~~~~~~~~~~~~~~~~~~~
                              |   18-24" deep
                              |   (concrete if possible --
                              |    Spokane frost depth is
                              |    ~24", so set below it
                              |    or expect frost heave
                              |    to tilt your camera)
                              +

        Battery lives IN the enclosure (rung A) or in a second
        box at the pole base (rung C) -- lower centre of gravity,
        and easier to swap without disturbing the camera aim.
```

**Frost heave is a real and often-missed issue here.** A pole set above the frost
line will tilt a few degrees each freeze-thaw cycle, and your carefully framed
shot will drift over the winter. Either set below ~24 inches, or accept that
you'll re-aim in spring, or use a driven ground socket that you can re-plumb.

### 8.2 Eave mount

```
        \                                    <- roof
         \
          \  [dome baffle]  <- against drop-in squirrels
           \______|__________
           |      |          |               <- soffit / fascia
           |  +===+========+ |
           |  | ENCLOSURE  | |               <- shaded by the eave already:
           |  |  [O]--->   | |                  a large thermal win, free
           |  +==+======+==+ |
           |     |      |    |
           |  +--+------+--+ |
           |  | PERCH+FEED | |
           |  +------------+ |

        Pros: mains/PoE trivially available (see 2.7); pre-shaded;
              best WiFi; no frost heave; no climbing route
        Cons: squirrels drop from the roof; you must be able to reach
              it for maintenance (you WILL be out there monthly);
              proximity to the house means window strikes are a risk

        Window strikes: do NOT site a feeder 5-15 ft from a window --
        that's the worst distance band. Either within 3 ft (birds can't
        build up speed) or beyond 30 ft.
```

**Recommendation: run the shakedown at the eave, deploy long-term at the pole.**
The eave gives you mains power and good WiFi while you're debugging everything
else, so you're only solving one problem at a time. Move to the pole once the
software and optics are settled and power is the only remaining variable.

---

## 9. Software Changes This Implies

Collected from the sections above, roughly in priority order. None are large.

| # | Change | Where | Why |
|---|---|---|---|
| 1 | Default `TRIGGER_TYPE` to `ir_beam`, not `pir` | `raspberry_pi_code/config.py:32` | §4.1 — PIR doesn't detect birds |
| 2 | Lock autofocus + set a shutter floor | `raspberry_pi_code/camera/pi_camera.py:28` | §5.3 — currently no AF config at all; the lens hunts |
| 3 | Stuck-beam / stuck-switch fault detection | `raspberry_pi_code/trigger/` | §4.4 — snow or debris = permanent trigger or trigger storm |
| 4 | Dawn/dusk scheduling + `POWER_OFF_ON_HALT=1` | new systemd timer | §2.4 — roughly 2× runtime for no hardware cost |
| 5 | Report SoC temperature + throttle flags with the heartbeat | Pi → `POST /devices/.../heartbeat` | §3.1 — you cannot debug thermal problems you can't see |
| 6 | Report battery voltage / percentage in the heartbeat | same | §2 — "when do I swap the pack" should be a dashboard answer, not a guess |
| 7 | Watchdog timer enabled | `/boot/firmware/config.txt` | An unattended outdoor Pi must self-recover from a hang |
| 8 | Logs to tmpfs; consider USB SSD boot | OS-level | §7.3 — SD corruption is the classic long-term killer |
| 9 | Adaptive debounce for flocking species | `raspberry_pi_code/pipeline.py` | §4.5 — nice-to-have, after the field trial |

Items 5 and 6 are worth calling out: **the frontend already has a Devices page.**
Surfacing temperature, throttle state and battery there turns every subsequent
question in this document from speculation into telemetry, and it's a small
change to a path you've already built and tested.

---

## 10. Staged Bring-Up Plan

Don't go from bench to backyard in one step. Each stage is designed to fail in a
way you can diagnose.

```
  STAGE 0 -- BENCH (indoors, mains)                             [ ~1 evening ]
    Close C4: wire the real trigger (perch switch) to BCM17.
    Confirm: one capture per press, correct debounce, full pipeline runs.
    Exit: C4 checked off in FLEDGE_ROADMAP.md.

  STAGE 1 -- WINDOWSILL (indoors, mains, real birds outside)    [ ~2 days ]
    Camera through a window at a temporary feeder.
    Confirm: focus lock, exposure, framing, and Tier 1 accuracy on
             REAL birds -- not the 20-image test set.
    Exit: you know your true top-1 rate on wild birds. This number
          matters more than anything else in this document and you
          do not have it yet.

  STAGE 2 -- SHELTERED OUTDOOR (eave/porch, mains)              [ ~1 week ]
    Full enclosure, real mounting, but power and WiFi are guaranteed.
    Confirm: condensation behaviour over 7 day/night cycles,
             thermal logging, squirrel interest, trigger reliability.
    Exit: no water inside, no throttling, no false-trigger storms.

  STAGE 3 -- BATTERY (same location, rung A pack)               [ ~3 days ]
    Change ONE variable: the power source.
    Confirm: measured runtime vs the 20 h prediction, no brownouts,
             bank doesn't auto-sleep (2.8).
    Exit: a real number for hours-per-charge.

  STAGE 4 -- YARD POLE                                          [ ~2 weeks ]
    Change ONE variable: the location.
    Confirm: WiFi RSSI holds, baffle works, offline queue drains
             correctly after a deliberate backend outage.
    Exit: two weeks unattended except for battery swaps.

  STAGE 5 -- WINTER                                             [ ongoing ]
    The real test. Cold-derated battery, snow, condensation,
    low sun angle, peak bird traffic.
```

**Stage 1 is the one people skip and shouldn't.** Your accuracy numbers
(20/20 top-1 on both tiers) come from a curated 20-image set. Real feeder
images — motion-blurred, partially occluded, backlit, at an angle, in snow —
are a different distribution, and knowing that gap *before* you're debugging it
through a battery-powered box on a pole is worth two days.

---

## 11. Shopping List

Minimum viable outdoor build, rung A power, perch-switch trigger:

| Item | Approx. | Notes |
|---|---|---|
| IP65 enclosure (Sixfab Pi outdoor, or a grey PVC junction box) | $25–40 | Light coloured. Bigger than you think. §3.4 |
| Pressure-equalisation vent (Gore PolyVent / Bud PMF) | $8 | **Do not skip.** §3.3 |
| Cable gland variety pack (PG7/PG9 nylon) + blanking plugs | $10 | Match gland range to cable diameter |
| Rechargeable silica gel desiccant, colour-indicating | $10 | 50 g, plus a spare to rotate |
| USB-C PD power bank, 25,000 mAh, **"always-on" / low-current mode** | $50 | §2.2 rung A, §2.8 |
| 5 A-rated / e-marked USB-C cable, short | $10 | Undersized cable = brownouts that look like software bugs |
| SPDT roller-lever microswitch (10-pack) | $8 | §4.3 |
| Aluminium plate + thermal pad | $12 | Pi heatsink → enclosure wall. §3.2 |
| 1-inch smooth steel feeder pole | $30 | Not wood |
| Wrap-around squirrel baffle, ≥15 in diameter | $30 | §6.1 |
| Flexible metal conduit + fittings, 10 ft | $15 | Cable protection. §6.3 |
| Acrylic/glass disc + clear silicone (if opaque enclosure) | $10 | Camera window. §5.2 |
| Black adhesive felt / foam (lens light seal) | $6 | §5.2 — small part, large effect |
| **Total** | **~$225** | |

Deferred until the shakedown tells you it's needed:

| Item | Approx. | Trigger to buy |
|---|---|---|
| 12 V 20 Ah LiFePO4 + low-temp-cutoff BMS + 5 A buck | $120 | Rung A swap interval is too short |
| 100 W solar panel + MPPT + steep-tilt mount | $180 | You're committed to the pole *and* to off-grid |
| Outdoor mesh node / directional antenna | $70 | Pole RSSI survey comes back worse than −75 dBm |
| PoE injector + splitter + outdoor Cat6 | $60 | You decide the eave is the permanent home (§2.7) |
| USB SSD boot drive | $30 | After your first SD card corruption, or before it |

---

## 12. Open Questions

Things this document can't decide for you:

1. **Is "no external power at the feeder" (PRD §5.4) still a requirement, or an
   inherited assumption?** It's the constraint driving the most cost and
   complexity here. If the eave is acceptable long-term, §2.7 removes most of
   this document's difficulty. Worth an explicit decision either way.
2. **Pole or eave as the permanent home?** They have opposite strengths, and §10
   suggests using both in sequence — but the long-term answer changes the
   battery, network, and baffle spend.
3. **Perch switch or IR beam?** The perch switch is more reliable and cheaper but
   only catches perched birds. If you want ground feeders and hovering birds,
   that's a beam (or two).
4. **How often are you willing to walk out there?** Every power decision reduces
   to this number. Weekly is easy and cheap; monthly needs rung C; never needs
   mains or a well-sized solar array.
5. **What's your real accuracy on wild birds?** Unknown until Stage 1. It may
   reorder these priorities entirely — if real-world top-1 is 70%, that's a bigger
   problem than any enclosure question.

---

## Sources

Climate and site data:
- [Spokane climate averages — usclimatedata](https://usclimatedata.com/climate/spokane/washington/united-states/uswa0422)
- [Spokane snowfall totals & averages — Current Results](https://www.currentresults.com/Weather/Washington/Places/spokane-snowfall-totals-snow-accumulation-averages.php)
- [Spokane recent annual temperature & precipitation — Current Results](https://www.currentresults.com/Yearly-Weather/USA/WA/Spokane/recent-annual-spokane-temperature-precipitation.php)
- [NWS Spokane climate tables (Cliplot)](https://www.weather.gov/otx/Cliplot)
- [Wildfire smoke — Spokane Regional Clean Air Agency](https://spokanecleanair.org/air-quality/wildfire-smoke/)
- [Spokane's hottest month on record — The Spokesman-Review](https://www.spokesman.com/stories/2024/aug/02/spokane-just-experienced-its-most-sweltering-month/)

Power:
- [Ring Quick Release Battery Pack](https://ring.com/products/quick-release-battery-pack)
- [Safety and compliance info, Quick Release Ultra Battery Pack — Ring](https://ring.com/support/articles/ie4td/safety-and-compliance-information-for-quick-release-ultra-battery-pack)
- [Raspberry Pi power consumption, all models compared (2026)](https://raspberry.tips/en/raspberrypi-tutorials/raspberry-pi-power-consumption-update-2026-all-models-compared)
- [Reducing Raspberry Pi 5's power consumption by 140× — Jeff Geerling](https://www.jeffgeerling.com/blog/2023/reducing-raspberry-pi-5s-power-consumption-140x/)
- [Raspberry Pi 5 RTC documentation](https://github.com/raspberrypi/documentation/blob/master/documentation/asciidoc/computers/raspberry-pi/rtc.adoc)
- [Pi 5 RTC auto wake/shutdown — Raspberry Pi Forums](https://forums.raspberrypi.com/viewtopic.php?t=364576)

Triggering:
- [PIR sensor to detect small birds — Electronics Lab forums](https://www.electronics-lab.com/forums/threads/p-i-r-sensor-to-detect-small-birds.136690/)
- [PIR sensitive enough to respond to a small bird — PICAXE forum](https://picaxeforum.co.uk/threads/p-i-r-sensitive-enough-to-respond-to-a-small-bird.11010/)
- [Bird camera motion detection technology explained — Avian Bliss](https://avianbliss.com/understanding-bird-camera-motion-detection-technology/)

Enclosures:
- [Sixfab IP65 outdoor project enclosure for Raspberry Pi](https://sixfab.com/product/raspberry-pi-ip65-outdoor-iot-project-enclosure/)
- [Outdoor enclosure for RPi + camera — Raspberry Pi Forums](https://forums.raspberrypi.com/viewtopic.php?t=51187)

Squirrels:
- [All about squirrel baffles — Wild Bird Habitat Store](https://wildbirdhabitatstore.com/more-about-squirrel-baffles/)
- [Feeder pole placement vs baffle](https://howtostopsquirrels.com/feeder-pole-placement-vs-baffle-block-squirrels/)
- [Squirrel-proof basics — The Wood Thrush Shop](http://www.thewoodthrushshop.com/squirrelproof-basics)
