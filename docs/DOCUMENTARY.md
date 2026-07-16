# BadmintonVR — Build Journal

*A personal logbook of the journey — hand-written, updated only when I feel like
marking something down. This is the story/notes version, in my own words. For
the precise "what's built and how to run it" technical ledger, see
[PROGRESS.md](PROGRESS.md) (that one gets updated every time something lands;
this one doesn't).*

---

## 2026-07-12 — Phase 1: the twin moves

Phone clip → MediaPipe pose → `skeleton.json` → a stick-figure twin replaying the
motion in Unity. Pose only, no court position yet — the twin just plays in place
at court center.

Looks okay. Nothing much to comment — it worked about as expected. Good enough to
build on.

---

## 2026-07-15 — Phase 2: calibration reality check

Today's lesson: **the capture matters more than the code.**

The `position_front.mp4` clip was shot with the **0.6× ultrawide lens, from
ground level.** Both turned out to be exactly the wrong choices for court
tracking:

- **0.6× ultrawide** bends straight lines (barrel distortion) — the painted court
  lines curve, so a flat-floor homography can never fit them cleanly.
- **From the ground**, the far side of the court is only a few pixels per meter,
  and — worse — this hall has **two badminton paint sets side by side**, which
  visually blur into one confusing mess from a low angle.

Result: corner tracking was very hard, and just plain wrong. The calibration (the
mapping from video pixels → court position) came out off, which threw off every
position downstream. Two pictures tell the whole story.

### `position_front_rectified.png` — the bird's-eye sanity check

![rectified top-down warp with expected grid](img/phase2_rectified.png)

I took the camera frame and used the calibration to **flatten it into a top-down
view**, then drew the *correct* regulation court grid (green) on top. If the
calibration were right, the real painted lines would sit straight under the green
grid.

They don't. The far line bows, there's an extra painted line about a metre past
where the baseline should be, and there are **four vertical lines on the right
where my court only has two** — those extras are the *neighbouring* court's paint.
A calibration that can't flatten the paint into a straight grid is a calibration
built on the wrong points.

### `position_front_recalib_guide.png` — caught in the act

![two stance frames showing the wrong-clicked corners](img/phase2_recalib_guide.png)

Two frames where I'm standing *on* a corner I know the name of:

- **Left (t = 12.4 s)** — standing on the real `lsl_sing_fl`. The red crosses (the
  points the calibration used) land right at my feet. ✔ The left side was
  labelled correctly.
- **Right (t = 19.6 s)** — standing on the real `lsl_sing_fr`. The red crosses are
  ~1.5–2 m off to my right, sitting on the **second paint set**. ✘ The right-side
  corners were clicked on the wrong court.

That one wrong cluster of points dragged the whole homography — near positions
ended up ~0.8 m off, and the far side ballooned out past the real baseline.

**Takeaway for next time:** shoot at **1.0× (no ultrawide), elevated (2.5 m+),
from the net position centred on the half** — and stand on a named line while
recording, so I physically can't mis-click the paint during calibration. New
video coming.
