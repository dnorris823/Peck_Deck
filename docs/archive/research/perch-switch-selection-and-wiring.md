# Perch switch: part selection, wiring to BCM17, and mounting (issue #44)

## The question

`OUTDOOR_DEPLOYMENT.md` §4.3 decided *an SPDT roller-lever microswitch*, "~$8 for
10", and sketched a hinged perch resting on it. It named no part number, no
terminal assignment, no pull-up value, and no mounting geometry. This note fills
those in.

Two constraints are premises here, not open questions. Contact orientation is
settled by issue #42 — **NO-to-ground, internal pull-up, FALLING edge** — so the
job below is to say *which physical terminals* that means and to sanity-check the
electrical consequences, not to re-litigate NO vs NC. Application-level arrival
suppression is settled at **15 s**; that is a *visit* window. Millisecond-scale
contact bounce is a separate concern and is in scope.

Sources are manufacturer datasheets (Omron, fetched from `omronfs.omron.com`),
Raspberry Pi's own RP1 and GPIO documentation, the `rpi-lgpio` and `lgpio` source
and docs, and peer-reviewed ornithology. Where a primary source does not exist —
and for two of the four questions it genuinely does not — that is stated rather
than smoothed over.

---

## Answers

**1. The part.** **Omron `SS-01GL2-E`** — SPDT hinge *roller* lever, gold-alloy
crossbar contacts, **OF max 0.08 N {8 gf}**, PT ≈ 4.8 mm at the lever, OT min
1.2 mm, IP40, 30,000,000 operations mechanical. ~**$4.77 @1 / $3.95 @10** at
DigiKey (80 in stock, ships US). **The ~$8/10-pack budget does not buy a usable
part.** The KW11/KW12/V-15 commodity family is roughly 1.47 N — ~18× the
operating force — which on a hinged perch means a chickadee must push the perch
down ~20 mm to trigger it (derivation in §1.3). It is also silver-contact, which
fails the electrical test in answer 2 by a factor of ~2,000. §4.3's named
fallback, **`D2F-01L`, is also far too stiff at 0.78 N {80 gf}** — see §1.4.

**2. Terminals and the falling edge.** The SS series marks its terminals
**`C` / `NO` / `NC`** on the switch body. Use the **C–NO** pair (the contact that
closes on actuation): **`C` → GND**, **`NO` → BCM17** via a 330 Ω series
resistor, **`NC` → leave unconnected and insulated**. Pin idles high through the
pull-up; landing closes C–NO and pulls BCM17 low; FALLING fires. **The electrical
sanity-check fails on the internal pull-up alone**: it sources only ~45–100 µA,
against Omron's minimum applicable load of **1 mA at 5 VDC** for these gold
crossbar contacts — 10–22× short. An external pull-up is not optional. Details
and the silver-contact comparison in §2.

**3. Pull-up and snubbing.** **Raspberry Pi has not published the RP1 GPIO
pull-up resistance.** The RP1 Peripherals datasheet documents the pull-up *enable
bit* and contains no resistance value anywhere; the official GPIO documentation
page tabulates BCM2835/6/7/RP3A0 (50–65 kΩ) and BCM2711 (33–73 kΩ) and has **no
Pi 5 / RP1 table at all**. Treat 33–73 kΩ as the closest published analogue and
label it unverified. Either way the conclusion is robust: use an **external
3.3 kΩ pull-up to 3.3 V** (1.0 mA, meets the micro-load spec) and keep `PUD_UP`
enabled as a harmless backstop. Add **330 Ω in series** to the pin for fault
protection. **No RC snubbing** — the datasheet contact bounce is ≤1 ms and
`lgpio`'s filter handles it in software. Optional 10 nF for RF hygiene, not
debounce. §3.

**4. `bouncetime` on `rpi-lgpio`.** It is **not** RPi.GPIO's post-hoc timestamp
rejection. `rpi-lgpio` passes `bouncetime * 1000` to `lgpio.gpio_set_debounce_micros`,
and `lgpio` implements a **stability filter in its own userspace alert thread**:
an edge is reported only if no further edge of the monitored type arrives within
the debounce window, and **the callback fires one full debounce period after the
physical edge**. `bouncetime=200` therefore costs **200 ms of latency on every
capture** for a switch whose datasheet bounce is ≤1 ms. Recommend **20–50 ms**.
The C3 loopback test's "hold LOW ~3 s → exactly 1 event" **does** behave as
expected — but two other cases in the #42 test table have traps under these
semantics, including one that yields **zero** events where the table expects one.
§4.

**5. Mounting.** Hinged perch, switch under it, **but not resting on it**. The
governing result is that minimum perch deflection is `δ = (OF / W_bird) × PT` and
is **independent of lever ratio** — you cannot trade force margin against
movement with a rigid lever. For `SS-01GL2-E` and an 11 g chickadee that is
**≈3.6 mm**, which peer-reviewed perch-compliance data puts comfortably in the
"birds don't care" zone. A stop must carry the perch's static weight (a plain
dowel resting on the lever would self-trigger by ~4×) and a second stop must cap
travel at ≤1.2 mm past the operating point so a squirrel cannot exceed rated
overtravel. §5.

---

## 1. The part

### 1.1 What the commodity 10-pack actually is

There is no manufacturer datasheet for "KW11-3Z". I looked: the part is a
generic Chinese commodity item sold by many vendors under the same designation,
and the vendor page that search engines return as a datasheet
([gangyuantech.com](https://www.gangyuantech.com/kw11-3z-micro-switch-datasheet_sp))
resolves to "0 results found". Listings agree only on the marketing figures —
**SPDT, 5 A at 125/250 VAC, ~1,000,000 cycles**
([representative vendor listing](https://www.amazon.com/Twidec-Switch-Action-Button-KW11-3Z08/dp/B07NZZ6PYL)).
Operating force is not published by anyone.

That "5 A at 250 VAC" rating is the useful clue, because it identifies the family
being cloned: Omron's **V** series miniature basic switch, whose real datasheet
*is* available. From it:

- Operating-force codes: **`6` = 3.92 N {400 gf}, `5` = 1.96 N {200 gf},
  `4` = 0.98 N {100 gf}**, with the base part (no code) at 1.47 N {150 gf}.
  "Note: These values are for the pin plunger models."
- Contact material: **Silver alloy**, gap 1 mm.
- **"Minimum applicable load (reference value): DC5V 160mA"**
- Degree of protection: **IEC IP40**.

[Omron V series datasheet (`en-v.pdf`)](https://omronfs.omron.com/en_US/ecb/products/pdf/en-v.pdf)

So the commodity part is a ~1–1.5 N switch with silver contacts rated for a
minimum of 160 mA. Both numbers disqualify it, independently, and §1.3 and §2
quantify by how much.

### 1.2 The recommendation

**Omron `SS-01GL2-E`** — from the SS series datasheet
([`en-ss.pdf`](https://omronfs.omron.com/en_US/ecb/products/pdf/en-ss.pdf)):

| Spec | Value | Source |
|---|---|---|
| Contact form | SPDT, terminals marked **`C` / `NO` / `NC`** | Contact-form diagram, and the dimensional drawing |
| Actuator | Hinge roller lever (code `GL2`), stainless-steel lever, polyacetal resin roller | Model number legend |
| Rating | `01` = **30 VDC 0.1 A** | Model number legend |
| **Operating force OF max** | **0.08 N {8 gf}** | Hinge roller lever table |
| **Release force RF min** | **0.01 N {1 gf}** (reference value) | same |
| Overtravel OT min | **1.2 mm** | same |
| Movement differential MD max | **0.8 mm** | same |
| Free position FP max | 19.3 mm | same |
| Operating position OP | 14.5 ± 0.8 mm | same |
| ⇒ **Pretravel (FP − OP)** | **≈ 4.8 mm** at the lever | derived |
| Contact material | **Crossbar, gold alloy**, gap 0.25 mm | Contact Specifications table |
| **Minimum applicable load** | **5 VDC 1 mA** (reference value) | same |
| Degree of protection | **IEC IP40** | Characteristics table |
| Durability, mechanical | **30,000,000 operations min.** | Characteristics table; corroborated by DigiKey's listing |
| Ambient operating temperature | −25 °C to +85 °C | Characteristics table |
| Terminals | Solder terminals (`-T` suffix = quick-connect #110, `D` = PCB) | Model number legend |

Price and availability, [DigiKey `SS-01GL2-E`](https://www.digikey.com/en/products/detail/omron-electronics-inc-emc-div/SS-01GL2-E/369850):
**$4.77 @1, $3.95 @10, $3.66 @25**, 80 in stock, ships from Thief River Falls,
MN. Note the listed **manufacturer lead time of 26 weeks** — buy spares in the
same order rather than assuming a reorder is quick.

The datasheet's model legend makes the `-E` suffix the load-bearing part of the
number: `None` = 1.47 N {150 gf}, `-F` = 0.49 N {50 gf} (0.1 A, 5 A), **`-E` =
0.25 N {25 gf} (0.1 A)** — those being pin-plunger figures, which the lever
geometry then reduces to the 0.08 N above. **Ordering `SS-01GL2` without `-E`
gets you a 0.49 N switch**, six times stiffer, which will not work.

Two acceptable variants of the same switch:

- **`SS-01GL-E`** — plain hinge lever instead of roller. Identical force and
  travel (OF max 0.08 N, RF min 0.01 N, OT min 1.2 mm, MD max 0.8 mm, FP 13.6 mm,
  OP 8.8 ± 0.8 mm ⇒ PT ≈ 4.8 mm). Usually cheaper. **The roller is still worth
  paying for**, and §4.3's instinct here was right even though its part number
  was not: a perch hinged at one end *arcs*, so its contact point translates
  across the lever as it descends. A roller turns that sliding into rolling.
- **`SS-01GL13-E`** — simulated roller lever (R1.3). OF max 0.08 N, FP 15.5 mm,
  OP 10.7 ± 0.8 mm ⇒ PT ≈ 4.8 mm. A moulded pseudo-roller; a middle option.

### 1.3 Working the force numbers

A black-capped chickadee's mass, from a peer-reviewed study that actually weighed
wild birds (University of Alberta Botanic Garden, Devon, Alberta; recaptures
after overwintering): **males 11.8–11.9 g, females 10.8–11.1 g**
([Bandivadekar et al. / PMC8293719](https://pmc.ncbi.nlm.nih.gov/articles/PMC8293719/)).
Cornell's All About Birds gives a range of 0.009–0.014 kg for the species,
consistent with this (their page returned HTTP 403 to direct fetch; the figure is
from search-result metadata and should be treated as corroboration, not as the
primary citation). **Take W = 11 g = 0.108 N.**

Now the geometry. Perch hinged at one end, switch under it at distance `d` from
the hinge, bird landing at distance `L`. Moment balance about the hinge gives
force at the switch `F_sw = W × (L/d)`, so putting the switch **close to the
hinge amplifies the force** — that is the obvious lever trick. But the same ratio
divides the travel: the perch tip must descend `δ_perch = δ_switch × (L/d)`.

Multiply them and the ratio cancels. For a rigid lossless lever the bird's work
equals the switch's work, `W × δ_perch = F_sw × δ_switch`, so at the operating
point:

> **δ_perch = (OF / W_bird) × PT**

**The minimum perch deflection is set entirely by the switch's operating force ×
pretravel product against the bird's weight, and is independent of lever ratio.**
You cannot arrange your way out of a stiff switch. This is the single number that
decides the part:

| Part | OF max | PT (FP − OP) | **δ_perch for an 11 g chickadee** |
|---|---|---|---|
| **`SS-01GL2-E`** (recommended) | **0.08 N** | 4.8 mm | **3.6 mm** |
| `SS-01GL2-F` | 0.16 N | 4.8 mm | 7.1 mm |
| `D2F-01FL` (hinge lever, low OF) | 0.25 N | ≈3.2 mm | 7.4 mm |
| `SS-01GL2` (no `-E`/`-F`) | 0.49 N | 4.8 mm | 21.8 mm |
| `D2F-01FL2` (hinge roller, low OF) | 0.39 N | ≈3.5 mm | 12.6 mm |
| `D2HW-…22…` (sealed, IP67) | 0.5 N | ≈2.2 mm | 10.2 mm |
| **`D2F-01L`** (§4.3's named part) | **0.78 N** | ≈3.2 mm | **23 mm** |
| **KW11/KW12/V-15 class** | **≈1.47 N** | ≈1.5 mm | **≈20 mm** |

**This is a derived, first-principles result, not a datasheet figure.** It
assumes a rigid lever, no friction, no return spring, and the bird's full weight
delivered statically at one point. All four assumptions are optimistic, so treat
3.6 mm as a floor and verify on the bench. §5.3 explains how preload beats it.

So: the commodity 10-pack would need a chickadee to depress the perch **two
centimetres**. That is not a perch, it is a lever the bird would have to ride
down. Answering the ticket's question directly — **no, the ~$8/10-pack
roller-lever parts are not light enough, and the gap is not marginal, it is
about 18× in force and about 6× in resulting perch travel.** The alternative
costs ~$40 for 10, or ~$4.77 for one.

### 1.4 Sealed vs open, honestly

`SS-01GL2-E` is **IP40** — dust-protected, not water-protected. So is the D2F
family, and so is the V family. Every low-force Omron part I found is IP40.

The sealed option is the **D2HW** series
([`en-d2hw.pdf`](https://omronfs.omron.com/en_US/ecb/products/pdf/en-d2hw.pdf)):
**IEC IP67**, gold-alloy contacts, same **5 VDC 1 mA** minimum applicable load.
The tradeoff the ticket asked about is real and quantifiable: **the lightest
D2HW lever variant is OF max 0.5 N {50 gf}**, against 0.08 N for the `SS-01GL2-E`.
**Sealing costs 6.25× the operating force**, which by the formula above turns a
3.6 mm perch deflection into 10.2 mm.

For **Stage 1 this does not matter** — it is an indoor windowsill, shooting
through glass. Buy the IP40 part now. When the build moves outdoors, the honest
options are (a) accept a 10 mm perch throw with a D2HW, (b) keep the light switch
and seal the *enclosure* rather than the switch, putting the lever through a
gland or bellows, or (c) accept IP40 with §4.3's silicone-at-the-wire-entry
approach and treat the switch as a consumable. Option (b) is the one that keeps
the mechanics good, and it is an enclosure problem, which this map has already
scoped out.

---

## 2. Terminals and the falling edge

### 2.1 Which terminals

Omron marks SPDT basic switches **`COM` / `NO` / `NC`** (D2F contact-form
diagram) and **`C` / `NO` / `NC`** (SS series dimensional drawing) — same three
terminals, `C` and `COM` being the same common/moving contact.

Given the settled orientation (the normally-open contact is the one used, closing
to ground, so the pin falls):

```
    3V3 ──[ 3.3 kΩ ]──┬──────────────────────────  (external pull-up)
                      │
                      ├──[ 330 Ω ]── BCM17 (header pin 11), PUD_UP also enabled
                      │
                     NO ─┐
                         │  SS-01GL2-E   (C–NO closes when a bird lands)
                      C ─┘
                      │
                     GND
                      
                     NC ── leave unconnected, insulated
```

- **`C` → GND**
- **`NO` → BCM17**, through 330 Ω
- **`NC` → not connected**

"NO-to-ground" names *which contact pair* is used; it does not fix which end of
that pair lands on which rail, and a dry contact is electrically symmetric, so
either assignment produces the same falling edge. **`C` → GND is the better of
the two** for one concrete reason: `NC` is permanently connected to the moving
blade, i.e. to `C`. Put `C` on GND and the unused `NC` stub sits at ground
potential — harmless. Put `C` on BCM17 instead and the unused `NC` stub becomes a
floating antenna hanging directly off the signal line whenever the switch is at
rest, which is *most of the time*. Leave `NC` open and insulated; do not tie it
to 3.3 V, which buys nothing here and only creates a way to short the rail if a
contact ever fails make-before-break.

### 2.2 The closed-circuit current — this fails as specified

This is the real failure mode the ticket flagged, and it is worse than expected.

Closed-circuit current through the pull-up is `3.3 V / R`. Using the closest
published Raspberry Pi figures (see §3.1 for why they are only an analogue):

| R_pull-up | Current when the bird is on the perch |
|---|---|
| 33 kΩ | 100 µA |
| 50 kΩ | 66 µA |
| 73 kΩ | 45 µA |

Against Omron's spec, quoted verbatim from the SS series Contact Specifications
table for `SS-01` models: **"Minimum applicable load (reference value): 5 VDC
1 mA"**, with gold-alloy crossbar contacts. The D2F and D2HW datasheets give the
identical 1 mA at 5 VDC for their gold crossbar parts.

**The internal pull-up alone delivers 45–100 µA — 10 to 22× below the minimum
applicable load, across the entire published resistance range.** There is no
value in the range at which it passes. It is not a marginal call.

The datasheets are explicit about what that means. From the D2F "Using Micro
Loads" precaution:

> "Using a model for ordinary loads to open or close the contact of a micro load
> circuit may result in faulty contact. … The minimum applicable load is the
> N-level reference value. This value indicates the malfunction reference level
> for the reliability level of 60% (λ60). (JIS C5003). The equation
> λ60 = 0.5×10⁻⁶/operation, indicates that the estimated malfunction rate is
> less than 1/2,000,000 operations with a reliability level of 60%."

So the 1 mA figure is a *characterised reliability boundary*, not a hard cliff —
below it Omron simply stops making a claim. That is precisely the shape of the
failure the ticket anticipated: not a switch that never works, but one that
works on the bench and then intermittently fails to conduct months later, with
nothing in the logs to distinguish it from "no bird landed".

And the contact metal matters exactly as suspected. Silver-alloy parts —
including every KW11/KW12/V-15-class commodity switch — specify **160 mA at
5 VDC** (V series) or **100 mA at 5 VDC** (D2F silver models). Against 45–100 µA
that is a shortfall of roughly **1,600–3,500×**. Silver forms sulphide and oxide
films that need meaningful current and voltage to break through; gold crossbar
contacts exist specifically so that microamp-to-milliamp circuits wet reliably.
**Choosing a gold-contact part is not an upgrade here, it is a requirement**, and
it is a second independent reason the commodity 10-pack fails.

### 2.3 The fix

**External 3.3 kΩ pull-up to 3.3 V**: `3.3 V / 3.3 kΩ = 1.0 mA`, which meets the
1 mA figure exactly. 2.2 kΩ (1.5 mA) buys margin at negligible cost. Power burned
while a bird sits on the perch is 3.3 mW / 5.0 mW — irrelevant on mains, and this
map has already decided mains power on a covered deck.

Keep `PUD_UP` set as well. In parallel with 3.3 kΩ it changes the current by ~3%
(3.1 kΩ combined ⇒ 1.07 mA) and it means the pin is still defined if the external
resistor is ever disconnected or the daughterboard unplugged. It costs nothing.

**One caveat, stated plainly**: Omron characterises the minimum applicable load
at **5 VDC**, and the micro-load graph's operating region is bounded in both
current *and* voltage. Running at 3.3 V puts us below the plotted line. Matching
the *current* is the important half — 1 mA is the number that determines whether
the contact wets — but the lower voltage is slightly less able to punch through
any surface film, so this is a small residual risk rather than a clean pass. Gold
crossbar contacts are chosen precisely because they do not grow the film in
question, which is why I am comfortable recommending it, but **it is not a
datasheet-guaranteed operating point and should be listed as such.**

Electrical life is a non-issue at these currents: the binding limit is
**mechanical, 30,000,000 operations minimum**. At even 200 visits a day that is
over 400 years.

---

## 3. Pull-up value, snubbing, and pin protection

### 3.1 What Raspberry Pi actually publishes for RP1 — nothing

The ticket asked for the internal pull-up resistance of an RP1/Pi 5 GPIO pad from
Raspberry Pi's own documentation, and warned against assuming the BCM2711 figure
carries over. **It does not carry over, and there is no RP1 figure to replace it
with.**

The **RP1 Peripherals datasheet** (build-date 2023-11-07) describes the pad in
§3.1.3 "Pads":

> "Each GPIO is connected via a bidirectional CMOS pad… The GPIOs offer:
> • Fault-tolerant operation - very little current flows into the pin whilst it
> is below 3.63V and IOVDD is 0V • Output drive strength of 2mA, 4mA, 8mA or 12mA
> • Optional input Schmitt trigger hysteresis • Optional output slew rate limiter
> • **Integrated pull-up, pull-down, bus-keeper or high-impedance behaviour when
> the output drive is disabled** • Input buffer disable… • ESD rated to 4kV HBM,
> 500V CDM, 200V MM"

and Table 21 documents bit 3 as **`PUE` — "Pull up enable"** and bit 2 as
**`PDE` — "Pull down enable"**. That is the whole of it. **Searching the extracted
text of the entire datasheet for "ohm", "Ω", "resistance" and "resistor" returns
zero matches.** Raspberry Pi documents the control bit and not the value.

[RP1 Peripherals datasheet](https://datasheets.raspberrypi.com/rp1/rp1-peripherals.pdf)
(redirects to `pip-assets.raspberrypi.com/.../RP-008370-DS-1-rp1-peripherals.pdf`)

The official **GPIO documentation page** carries two voltage-specification tables
and neither is for the Pi 5:

- "for BCM2835, BCM2836, BCM2837 and RP3A0-based products" — **R_PU: min 50,
  max 65 kΩ**
- "for BCM2711-based products (4-series devices)" — **R_PU: min 33, max 73 kΩ**

The page contains **no occurrence of "RP1", "Pi 5", "5-series" or "BCM2712"**,
and still opens its pad section with "The GPIO connections on the BCM2835
package…". It has not been updated for Pi 5.

[`gpio-on-raspberry-pi.adoc`, raspberrypi/documentation](https://github.com/raspberrypi/documentation/blob/master/documentation/asciidoc/computers/raspberry-pi/gpio-on-raspberry-pi.adoc)

**Verdict: the RP1 internal pull-up resistance is unpublished.** Use **33–73 kΩ**
(the BCM2711 range) as a working analogue and label it an assumption. It happens
not to matter, because §2.2's conclusion holds across a range far wider than the
uncertainty: anything from 10 kΩ to 100 kΩ fails the 1 mA micro-load spec.

If a number is ever needed for real, it is measurable on the bench in one step:
enable `PUD_UP`, tie the pin to ground through a known resistor `R_test`
(say 10 kΩ), measure the pin voltage `V`, and `R_PU = R_test × (3.3 − V) / V`.

### 3.2 Series resistor — yes, 330 Ω

The RP1 pads are "ESD rated to 4kV HBM, 500V CDM, 200V MM" and are fault-tolerant
below 3.63 V, so ESD is not the concern on a 0.3–1 m indoor run. The concern is
the ordinary software fault: BCM17 accidentally configured as an **output driving
high** while the switch is closed, which shorts the pad to ground through its own
drive transistor. A series resistor bounds that current.

**330 Ω** is the right value, and the constraint that picks it is the *low-level
voltage*, not the fault current. With a 3.3 kΩ pull-up, the series resistor forms
a divider when the switch is closed:

| R_series | V at pin when closed | Fault current if driven high |
|---|---|---|
| 1 kΩ | 3.3 × 1/(1+3.3) = **0.77 V** | 3.3 mA |
| **330 Ω** | 3.3 × 0.33/(0.33+3.3) = **0.30 V** | **10 mA** |
| 100 Ω | 0.10 V | 33 mA |

1 kΩ is **too big**: 0.77 V is right on top of BCM2711's `V_IL` max of 0.8 V, so
the switch might not read as low at all. 330 Ω gives 0.30 V with wide margin and
holds the fault current to 10 mA, inside the pad's 2/4/8/12 mA programmable drive
range. (RP1's own `V_IL` is unpublished — same gap as §3.1 — so BCM2711's 0.8 V
is the conservative proxy. 0.30 V clears any plausible threshold.)

### 3.3 RC snubbing — not wanted

Two facts settle this.

First, the switch barely bounces. The D2F datasheet states it outright:
**"Close or open circuit of the contact is 1ms max."** These are snap-action
mechanisms with a 0.25 mm contact gap; sub-millisecond bounce is what they are
built for.

Second, `lgpio` already implements a stability filter in software with
microsecond resolution (§4), and it is strictly better at this than an RC network
because it does not distort the edge — it just refuses to report an unstable one.

So: **software debounce is sufficient; no RC debounce network.** Adding one would
slow the falling edge, add a component that can drift, and duplicate a filter
that already exists.

The one optional passive worth considering is a **10 nF cap from the pin to GND**
as RF hygiene on the run, not as debounce. With 330 Ω series that is a 3.3 µs
time constant on the falling edge and ~33 µs rising against the 3.3 kΩ pull-up —
both negligible against a 20 ms debounce window, while shunting anything the
wire picks up. Fit the pads, populate only if the bench shows noise.

**Note this is a mechanical contact, so the Schmitt trigger matters more than the
capacitor.** The RP1 pad has "Optional input Schmitt trigger hysteresis" and, per
Table 21, the `SCHMITT` bit's reset value is **`0x1`** — enabled by default. That
hysteresis is what keeps a slowly-crossing edge from producing a burst of
transitions, and it is on without anyone asking for it.

---

## 4. `bouncetime` under the `rpi-lgpio` shim

The Pi 5 GPIO backend here is `rpi-lgpio`, a shim presenting the `RPi.GPIO` API
over `lgpio`. Its `bouncetime=` is **not** the same mechanism as `RPi.GPIO`'s, and
the difference changes observed behaviour.

### 4.1 What the shim documents

`rpi-lgpio`'s "Differences" page — a primary source, written by the shim's author
to enumerate exactly this:

> "Debouncing of signals works fundamentally differently in RPi.GPIO, and in
> lgpio (the library underlying rpi-lgpio). RPi.GPIO debounces signals by
> tracking the last timestamp [and suppressing subsequent edges within the
> window]… lgpio (and thus rpi-lgpio) debounces by waiting for a signal to be
> stable."

with three worked consequences: identical results for a simple bounce (but
reported *later* by the debounce duration); **different counts** at shorter
debounce periods; and for a repeating signal faster than the debounce period,
"RPi.GPIO reports alternating edges while rpi-lgpio reports **none**". Its own
recommendation: "you may find shorter debounce periods preferable when working
with rpi-lgpio."

[rpi-lgpio Differences](https://rpi-lgpio.readthedocs.io/en/latest/differences.html)

### 4.2 What the code actually does

The shim converts milliseconds to microseconds and hands it straight to `lgpio`:

```python
if bouncetime is not None:
    _check(lgpio.gpio_set_debounce_micros(
        _chip, gpio, bouncetime * 1000))
alert = _Alert(gpio, edge, bouncetime)
```
[`RPi/GPIO/__init__.py`, `_set_alert`](https://github.com/waveform80/rpi-lgpio/blob/master/RPi/GPIO/__init__.py)

`lgpio`'s documented contract for that call:

> "This sets the debounce time for a GPIO. … **This only affects alerts.** An
> alert will only be issued if the edge has been stable for at least debounce
> microseconds. Generally this is used to debounce mechanical switches (e.g.
> contact bounce). **Note that level changes will be timestamped debounce
> microseconds after the actual level change.**"

[`lgGpioSetDebounce`, abyz.me.uk/lg](https://abyz.me.uk/lg/lgpio.html)

And crucially it is **not** the kernel's `gpiod` debounce — `lgpio` implements it
in its own userspace alert thread. From the source, with its own rules verbatim:

```c
if (p->debounce_nanos && !p->debounced)
{
   /*
   Only report stable edges.  A stable edge is defined as one
   which has not changed for debounce nanoseconds.
   ...
   2.  If only falling edges are being monitored a falling edge
   is reported if and only no other edge is detected for at
   least debounce nanoseconds after it occurred.
   ...
   */
   nano_diff = ts - p->last_evt_ts;
   if (nano_diff > p->debounce_nanos)
   {
      ...
      aBuf[*cp].report.timestamp = p->last_evt_ts + p->debounce_nanos;
```
[`lgPthAlerts.c`, joan2937/lg](https://github.com/joan2937/lg/blob/master/lgPthAlerts.c)

One more detail that matters for interpreting rule 2: when `FALLING` is
requested, `lgpio` asks the kernel for **falling edges only** —
`if (s & LG_FALLING_EDGE) f |= GPIO_V2_LINE_FLAG_EDGE_FALLING;`
([`lgGpio.c`](https://github.com/joan2937/lg/blob/master/lgGpio.c)) — so the
filter never sees the release edge at all.

### 4.3 What that means for this build

- **`bouncetime=200` does not require the line to stay LOW for 200 ms.** It
  requires that no *further falling edge* arrive within 200 ms. A bird that lands
  and departs in 30 ms still produces exactly one event, because the rising edge
  is invisible to the filter. Good news, and not obvious from the API.
- **Every event is delivered `bouncetime` late.** With 200 ms, the camera is not
  even *told* to shoot until 200 ms after the bird touched down. Against a
  datasheet contact bounce of ≤1 ms, that is ~200× more suppression than the part
  needs, paid for in latency on the one thing the system exists to photograph.
- **Recommend `bouncetime=20`** (20× the datasheet bounce, 20 ms latency). If
  bench testing shows the *perch* ringing — a hinged mass-spring will oscillate
  on landing in a way the contact spec says nothing about — go to 50 ms. Not
  more: the 15 s arrival suppression from #42 is the real backstop against a
  chattering visit, so `bouncetime`'s only remaining job is to stop a single
  landing from queueing two captures.

### 4.4 Consequences for the C3 loopback suite

The #42 test table, re-read against these semantics:

| Case | Expected | Under `rpi-lgpio`/`lgpio` |
|---|---|---|
| quiet after setup | 0 | ✅ 0 |
| single FALLING | 1 | ✅ 1 — **but delivered `bouncetime` later** |
| **HELD LOW ~3 s** | **1** | ✅ **1.** One falling edge, no successor, one alert at `t + bouncetime`. The held-contact case behaves as the ticket assumed. |
| release (RISING) | 0 | ✅ 0 — the kernel is not even asked for rising edges |
| bounce burst <200 ms | 1 | ⚠️ **Depends on the burst.** One alert, timestamped from the **last** edge, not the first. And if the burst *repeats* faster than `bouncetime` for longer than `bouncetime` — e.g. edges every 10 ms for 3 s with `bouncetime=200` — the answer is **0 events, not 1**, exactly the third scenario in the shim's own docs. |
| two spaced FALLING | 2 | ⚠️ Only if the spacing **exceeds `bouncetime`**. |

Two concrete actions for whoever writes that suite: **assert after a sleep longer
than `bouncetime`**, or a correct implementation will read as zero events; and
**pick the bounce-burst timing deliberately**, because "a burst" is now two
different tests with two different right answers.

### 4.5 Other shim gotchas that apply here

- **Callbacks run on `lgpio`'s alert thread**, via `lgpio.callback(...)` in
  `_Alert.__init__`. The existing `IRBeamTrigger._callback` already does
  `self._loop.call_soon_threadsafe(...)` — that is correct and load-bearing, not
  decoration. Keep it in `PerchSwitchTrigger`.
- **Exceptions inside a callback are printed, not raised.** The shim catches them
  and does `print(exc, file=sys.stderr)` with the comment "Bug compatibility:
  this is how RPi.GPIO operates". A failing callback will not surface as a
  crash — log inside the callback, don't rely on the exception escaping.
- **Re-calling `add_event_detect` with a different `bouncetime` raises**
  `RuntimeError('Conflicting edge detection already enabled for this GPIO
  channel')` (`_get_alert`). Changing the debounce value at runtime means
  `remove_event_detect` first.
- **Two processes cannot share BCM17.** "Two processes using RPi.GPIO can happily
  control the same pin. This is simply not permitted by the Linux gpiochip device
  and will fail under rpi-lgpio." The loopback test script and the main pipeline
  cannot both be running. Worth a line in the runbook, since this is a behaviour
  change from `RPi.GPIO` that will present as a confusing failure.
- `PUD_UP` maps cleanly: `PUD_UP → lgpio.SET_PULL_UP → GPIO_V2_LINE_FLAG_BIAS_PULL_UP`,
  applied on the same `gpio_claim_alert` call. Nothing surprising.

---

## 5. Mechanical mounting

### 5.1 What §4.3's diagram gets wrong

`OUTDOOR_DEPLOYMENT.md` §4.3 sketches a dowel hinged at one end, resting on the
switch, deflecting "~1 mm" when a bird lands. Two of those three are wrong.

**Wrong: "~1 mm" deflection.** `SS-01GL2-E` has ~4.8 mm of lever pretravel, and
§1.3's energy argument puts the minimum perch deflection at **3.6 mm** for an
11 g bird — and that is the best case, with the lightest switch available. With
the D2F-01L §4.3 names, it is 23 mm. The diagram's "small deflection (~1 mm)" is
off by 4× for the right part and 20× for the part it names.

**Wrong: the perch resting on the switch.** Take §4.3's own dowel: 16 mm
diameter × 150 mm of birch (~0.65 g/cm³) is ~30 cm³, ~20 g, with its centre of
mass at 75 mm from the hinge. If the switch sits at 50 mm from the hinge, the
static force it carries from the *perch alone* is 20 gf × 75/50 = **~30 gf** —
nearly **4× the switch's 8 gf operating force**. The perch would hold the switch
permanently closed, before any bird arrives. A "light return spring", as §4.3
suggests, is not a tuning refinement; without it the mechanism does not have a
resting state at all.

Right: the hinge, the roller lever, and the falling edge.

### 5.2 The geometry that works

```
     SIDE VIEW                       bird lands here
                                          |
                                          v
     hinge                        ========================  perch dowel
       O========================================
       |         |          |
       |    [ roller ]      |
       |    [ switch ]      |          ^ UPPER STOP: carries the perch's
       |         ^          |            own weight so the switch idles
       |         |          |            just short of its operating point
       |         d          |
       |                    +-- LOWER STOP: hard limit, ≤1.2 mm past
       |                        the operating point (OT min), so a
       |                        squirrel cannot exceed rated overtravel
```

Four elements, each doing one job:

1. **Hinge.** A stiff pivot at one end. Play in the hinge shows up directly as
   perch wobble, which §5.4 says is the thing to avoid — prefer a small ball-bearing
   pivot or a shouldered screw in a reamed hole over a loose pin.
2. **Roller lever contact at distance `d`.** Because the perch arcs, the contact
   point slides; the roller converts that to rolling. Put `d` where the geometry
   is convenient rather than optimising it — §1.3 showed the lever ratio does not
   change the deflection the bird feels.
3. **Upper stop / return spring — the important one.** This carries the perch's
   static weight. Tune it so the switch idles just *short* of its operating point,
   with a small residual force (2–4 gf of the 8 gf OF). This is what makes the
   design work, and §5.3 explains why.
4. **Lower stop.** A hard mechanical limit that catches the perch **≤1.2 mm past
   the operating point** (OT min for this part). Everything heavier than a bird —
   §4.3 explicitly wants squirrels to trigger it — then lands on the stop, not on
   the switch. Without this, the first squirrel is also the last day the switch
   works. This is the single most important protective detail in the build, and
   §4.3 mentions travel limits without giving the number.

### 5.3 Preload is what buys both light touch and a solid perch

§1.3's `δ_perch = (OF/W) × PT` assumes the switch starts at its free position and
the bird supplies the whole pretravel. **Preload changes the `PT` term.** If the
upper stop is set so the lever already sits, say, 4 mm into its 4.8 mm pretravel,
the bird only has to supply the last 0.8 mm — and the perch deflection drops to
well under a millimetre, which is where §4.3 wanted to be all along.

That is the real design lever, and it comes with an honest cost: **the closer the
preload is to the operating point, the more the mechanism drifts into
self-triggering.** Wood swells with humidity, springs relax, temperature moves
everything. Indoors, on a windowsill, with mains power and no wind, this is a
benign tradeoff and can be tuned aggressively. Outdoors it is the whole problem,
and it is the reason a wind margin has to be re-derived at that point rather than
inherited.

Rough order of magnitude for the outdoor question, flagged as an estimate and not
a result: a 16 mm × 150 mm dowel presents ~24 cm² of side area; at 10 m/s
(22 mph) with `Cd ≈ 1.2`, drag is `½ρv²C_dA ≈ 0.18 N ≈ 18 gf` — about **2× the
switch's 8 gf OF**. Most of that is horizontal and a vertically-pivoting perch
rejects most of it, but the margin is clearly thin, and the coupling geometry is
not modelled here. **Stage 1 is indoors, so this is deferred, not solved.**

### 5.4 Will birds still land on it?

This is the part the ticket was right to insist on sourcing rather than
asserting, and the literature has a direct answer.

The relevant variable is **compliance** (springiness), not diameter. A study of
diamond doves taking off from and landing on perches of matched 5 mm diameter but
different flexural rigidity found:

> "Take-off velocities were lower with more compliant perches. Take-off resultant
> velocities were significantly greater on the perch with the lowest compliance,
> steel."

with the tested perches deflecting **2.6 cm (wood, EI = 0.39 Nm²), 0.5 cm
(aluminium, EI = 2.12 Nm²) and 0.2 cm (steel, EI = 6.14 Nm²)**. And in the wild,

> "Birds were located on perches averaging 2.3 ± 1.4 cm in diameter"

against 0.9 ± 1.4 cm available, from which the authors conclude that "free-living
diamond doves avoid the negative impacts of compliance by preferentially
selecting perches of larger diameter, which tend to be stiffer."

[Coping with compliance during take-off and landing in the diamond dove, PLOS ONE / PMC6059395](https://pmc.ncbi.nlm.nih.gov/articles/PMC6059395/)

**This calibrates the design precisely.** The steel perch deflected **2 mm** and
was the *best* performer; the problem case deflected 26 mm. Our computed 3.6 mm —
or well under 1 mm with preload — sits at the good end of a bracket that
experiment actually measured. The map's intuition that "1 mm of movement is fine
but wobbly is not" is **supported**, and now has a number: **a few millimetres is
demonstrably fine; a couple of centimetres measurably degrades take-off.** This
is also the strongest argument against the commodity switch, which lands at
~20 mm — right on the failing end.

Diameter and texture, by contrast, the bird handles for you. Landing Pacific
parrotlets "exhibit stereotyped leg and wing dynamics regardless of perch
diameter and texture", adapting only their foot, toe and claw kinematics on
contact across nine surfaces from Teflon to sandpaper
([Birds land reliably on complex surfaces, eLife / PMC6684272](https://pmc.ncbi.nlm.nih.gov/articles/PMC6684272/)).

Two caveats worth being explicit about. Both studies are of **doves and
parrotlets, not chickadees** — a 50 g dove and an 11 g chickadee load a perch
very differently, and I found no compliance study on small passerines. And I
found **no primary source for an optimal feeder-perch diameter for chickadees**;
Cornell's feeder guidance discusses short perches as a way to *exclude* large
species, not an optimum for small ones
([All About Birds, choosing a feeder](https://www.allaboutbirds.org/news/how-to-choose-the-right-kind-of-bird-feeder/)).
The dove figure (2.3 cm preferred) is the only measured preference I have, and it
is for a much larger bird. §4.3's implicit dowel-sized perch is not contradicted
by anything I found, but it is not *supported* by a primary source either — treat
diameter as a free variable to be settled by watching the Stage 1 feed.

---

## Contradictions with `OUTDOOR_DEPLOYMENT.md` §4.3

Stated plainly, as the ticket asked:

1. **The named part is wrong.** "Omron D2F-01L" is **OF max 0.78 N {80 gf}** —
   about seven times a whole chickadee's body weight — implying ~23 mm of perch
   travel. The D2F family in general is the wrong family; the right one is the SS
   series with the `-E` force code.
2. **"~$8 for 10" does not buy a usable switch.** The correct part is ~$40/10 or
   $4.77 for one. The KW11/KW12 clones are ~18× too stiff *and* silver-contact.
3. **"the perch deflects a millimetre" is optimistic by ~4×** for the best
   available part (3.6 mm), unless preload is used — which §4.3 does not mention.
4. **The dowel cannot rest on the switch.** §4.3's own diagram shows exactly
   that, and a §4.3-sized dowel preloads the lever to ~4× its operating force.
   The return spring is mandatory, not a tuning option.
5. **"No code change" is not quite true.** The wiring works as-is, but
   `bouncetime=200` inherited from `IRBeamTrigger` costs 200 ms of latency under
   `rpi-lgpio`'s stability-filter semantics, for a switch that bounces ≤1 ms.
6. **§4.3 says nothing about an external pull-up**, and the internal one fails
   the switch's minimum applicable load by 10–22× regardless of which published
   resistance figure is assumed. This is the change most likely to be skipped and
   most likely to produce a slow, silent, months-later failure.

§4.3 got the important things right: mechanical switch over PIR, roller lever
over plain lever, falling edge into a pull-up, squirrels trigger it and that's
fine. The specifics all need replacing.

---

## Bill of materials (Stage 1)

| Item | Part | Qty | Notes |
|---|---|---|---|
| Switch | Omron **`SS-01GL2-E`** | 1 (+2 spare) | 26-week factory lead time; buy spares now |
| Pull-up | 3.3 kΩ, ¼ W, 1% | 1 | 2.2 kΩ acceptable for extra margin |
| Series/protection | 330 Ω, ¼ W | 1 | Do **not** use 1 kΩ — see §3.2 |
| RF hygiene (optional) | 10 nF ceramic | 1 | Fit the pads, populate only if needed |
| Mounting | M2 screws + washers | 2 | Omron: "Tighten the screws to a torque of 0.08 to 0.1 N·m" |

Code change to `raspberry_pi_code/trigger/` (shape only — the class rename is
#36's):

```python
GPIO.setmode(GPIO.BCM)
GPIO.setup(self._pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.add_event_detect(
    self._pin,
    GPIO.FALLING,
    callback=self._callback,
    bouncetime=20,   # was 200. Datasheet contact bounce is <=1 ms, and under
                     # rpi-lgpio every event is delivered bouncetime late.
)
```

---

## Open uncertainties

- **The RP1 internal pull-up resistance is unpublished by Raspberry Pi.** Neither
  the RP1 Peripherals datasheet (zero matches for "ohm"/"resistance"/"Ω") nor the
  official GPIO documentation page (which has no Pi 5 table at all) gives a
  value. 33–73 kΩ is borrowed from BCM2711 and is **an assumption**. It does not
  change any conclusion here, because the micro-load verdict holds across
  10–100 kΩ. Measurable on the bench in one step (§3.1) if it ever matters.
- **RP1's `V_IL`/`V_IH` are likewise unpublished.** §3.2's 330 Ω choice uses
  BCM2711's `V_IL` max of 0.8 V as a proxy. 0.30 V has margin against anything
  plausible, but the threshold itself is unconfirmed for this silicon.
- **`δ_perch = (OF/W) × PT` is derived, not sourced.** It is a rigid-lever,
  lossless, static, point-load idealisation. Friction, hinge stiction, spring
  force and the dynamics of an actual landing all push the real number up. Treat
  3.6 mm as a floor and measure it.
- **Where along the lever Omron applies OF is not resolved.** The datasheet's
  operating characteristics are "for operation in the A direction" with the point
  shown on a dimensional drawing that did not survive text extraction. If the
  perch contacts the lever somewhere other than the specified point, the
  effective OF changes by that lever ratio. **Verify on the bench with a small
  scale before committing the geometry.**
- **The 1 mA minimum applicable load is specified at 5 VDC, and we run at 3.3 V.**
  §2.3 argues this is acceptable for gold crossbar contacts and matches the
  current, but it is outside the characterised region and is not a
  datasheet-guaranteed operating point.
- **`SS-01` electrical durability could not be read unambiguously** — the
  Characteristics table's column alignment did not survive extraction (values
  50,000 / 200,000 / 100,000 across four model columns). Mechanical durability of
  30,000,000 is confirmed independently by DigiKey's listing, and at 1 mA the
  mechanical limit is the binding one, so this does not affect the
  recommendation.
- **No compliance or perch-diameter study on small passerines was found.** The
  numbers in §5.4 are from diamond doves (~50 g) and Pacific parrotlets. They
  bracket the answer usefully but a chickadee is 4–5× lighter, and the
  extrapolation is mine.
- **No primary datasheet exists for KW11-3Z/KW12.** The ~1.47 N figure used to
  disqualify them is inferred from the Omron V series they clone, matched on the
  5 A/250 VAC rating. If someone produces a real KW11 datasheet with a lower OF,
  the electrical objection (silver contacts, 160 mA minimum load) still stands
  independently.
- **The chickadee mass figure is from one Alberta population.** 10.8–11.9 g for
  overwintering birds; Cornell's species-wide range is 9–14 g. A 14 g bird has
  30% more margin than the calculations here assume, a 9 g bird has 18% less —
  the design should clear the light end, which at 3.6 mm × (11/9) ≈ 4.4 mm it
  still does.
- **Nothing here has been tested on hardware.** I read datasheets, source and
  papers; the Pi is a separate machine I cannot reach. Every mechanical number
  above wants a bench check with a gram scale and a dial indicator before parts
  are cut.

---

## Sources

**Switches (manufacturer datasheets)**
- [Omron SS series — Subminiature Basic Switch (`en-ss.pdf`)](https://omronfs.omron.com/en_US/ecb/products/pdf/en-ss.pdf) — model legend, per-actuator operating characteristics, contact specifications, minimum applicable load, micro-load precaution, IP40, durability.
- [Omron D2F series — Ultra Subminiature Basic Switch (`en-d2f.pdf`)](https://omronfs.omron.com/en_US/ecb/products/pdf/en-d2f.pdf) — COM/NO/NC labelling, gold vs silver minimum applicable load (1 mA / 100 mA at 5 VDC), "Close or open circuit of the contact is 1ms max.", "Using Micro Loads" / JIS C5003 λ60 definition, M2 mounting torque.
- [Omron V series — Miniature Basic Switch (`en-v.pdf`)](https://omronfs.omron.com/en_US/ecb/products/pdf/en-v.pdf) — the family the KW11/KW12 clones copy: OF codes, silver alloy, "Minimum applicable load (reference value): DC5V 160mA", IP40.
- [Omron D2HW series — Sealed Ultra Subminiature Basic Switch (`en-d2hw.pdf`)](https://omronfs.omron.com/en_US/ecb/products/pdf/en-d2hw.pdf) — IP67 alternative, gold alloy, 5 VDC 1 mA, lightest lever OF 0.5 N.
- [DigiKey — Omron `SS-01GL2-E`](https://www.digikey.com/en/products/detail/omron-electronics-inc-emc-div/SS-01GL2-E/369850) — US price/stock/lead time.
- [gangyuantech.com "KW11-3Z datasheet"](https://www.gangyuantech.com/kw11-3z-micro-switch-datasheet_sp) — cited as evidence of *absence*: returns "0 results found".

**Raspberry Pi hardware**
- [RP1 Peripherals datasheet](https://datasheets.raspberrypi.com/rp1/rp1-peripherals.pdf) — §3.1.3 "Pads" (drive strength, Schmitt trigger, ESD ratings, fault tolerance), Table 21 (`PUE`/`PDE`/`SCHMITT` bits and reset values). Contains **no** pull-up resistance value.
- [`gpio-on-raspberry-pi.adoc`, raspberrypi/documentation](https://github.com/raspberrypi/documentation/blob/master/documentation/asciidoc/computers/raspberry-pi/gpio-on-raspberry-pi.adoc) — GPIO voltage-specification tables for BCM2835/6/7/RP3A0 (R_PU 50–65 kΩ) and BCM2711 (R_PU 33–73 kΩ). **No Pi 5 / RP1 table.**

**GPIO software**
- [rpi-lgpio — Differences from RPi.GPIO](https://rpi-lgpio.readthedocs.io/en/latest/differences.html) — Debounce, Simultaneous Access, Alternate Pin Modes, PWM on inputs, Stack Traces, Pi Revision, GPIO Chip.
- [`RPi/GPIO/__init__.py`, waveform80/rpi-lgpio](https://github.com/waveform80/rpi-lgpio/blob/master/RPi/GPIO/__init__.py) — `_Alert`, `_set_alert`, `_get_alert`, `_check_bounce`, `add_event_detect`, `setup`/PUD mapping, callback exception handling.
- [`lgGpioSetDebounce` / `lgGpioClaimAlert`, abyz.me.uk/lg](https://abyz.me.uk/lg/lgpio.html) and [the Python binding docs](https://abyz.me.uk/lg/py_lgpio.html) — debounce contract and the timestamp-shift note.
- [`lgPthAlerts.c`, joan2937/lg](https://github.com/joan2937/lg/blob/master/lgPthAlerts.c) — the userspace stability-filter implementation and its three rules.
- [`lgGpio.c`, joan2937/lg](https://github.com/joan2937/lg/blob/master/lgGpio.c) — `LG_FALLING_EDGE → GPIO_V2_LINE_FLAG_EDGE_FALLING`, `lgGpioSetDebounce` bounds check.

**Ornithology**
- [No effect of passive integrated transponder tagging method on survival or body condition in a northern population of Black-capped Chickadees, *Ecology and Evolution* / PMC8293719](https://pmc.ncbi.nlm.nih.gov/articles/PMC8293719/) — measured masses of wild *Poecile atricapillus*: males 11.8–11.9 g, females 10.8–11.1 g.
- [Coping with compliance during take-off and landing in the diamond dove (*Geopelia cuneata*), *PLOS ONE* / PMC6059395](https://pmc.ncbi.nlm.nih.gov/articles/PMC6059395/) — perch compliance vs take-off velocity; deflections of 2.6 / 0.5 / 0.2 cm; wild perch-diameter selection 2.3 ± 1.4 cm vs 0.9 ± 1.4 cm available.
- [Birds land reliably on complex surfaces by adapting their foot-surface interactions upon contact, *eLife* / PMC6684272](https://pmc.ncbi.nlm.nih.gov/articles/PMC6684272/) — Pacific parrotlet landing dynamics stereotyped across perch diameter and texture.
- [Cornell Lab of Ornithology, All About Birds — How to Choose the Right Kind of Bird Feeder](https://www.allaboutbirds.org/news/how-to-choose-the-right-kind-of-bird-feeder/) — perch length as a species filter. (The Black-capped Chickadee species page, `allaboutbirds.org/guide/Black-capped_Chickadee/id`, returned HTTP 403 to direct fetch; its 0.009–0.014 kg range is cited as corroboration only.)
