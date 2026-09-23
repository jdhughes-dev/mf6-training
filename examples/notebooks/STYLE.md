# Notebook description style guide

How to write the markdown descriptions that accompany code cells in the training
notebooks under `examples/notebooks/`. The goal is a single, consistent voice
that a student with **no-to-moderate Python, FloPy, and MODFLOW 6 experience**
can follow in a live class and review on their own afterward.

The reference notebooks are
[`flopy-intro-gwf-only-a.ipynb`](flopy-intro-gwf-only-a.ipynb) (a guided model
build) and [`mf6-api-a.ipynb`](mf6-api-a.ipynb) (a concept walk-through). When in
doubt, match them.

## Where these rules come from

The prose rules below are J.D. Hughes' writing conventions, carried in the
`jdhughes-writing-style` and `jdhughes-code-style` plugins. A Claude Code session
editing these notebooks loads `jdhughes-writing-style` before a prose pass and
`jdhughes-code-style` before touching a paired `.py` helper module. The plugin
marketplace is private, so the rules that apply to notebooks are restated here
rather than linked, and this file is what a contributor without the plugins
follows.

The plugins describe manuscripts, which these notebooks are not. Where the two
disagree, this file wins, and it says so at the point of disagreement.

## The core rule

**Every meaningful code cell is preceded by a short markdown cell that answers
three things, in this order:**

1. **What** the cell does — one plain-language sentence.
2. **Why** it matters — the physical meaning or the modeling purpose (one
   sentence; omit only for truly mechanical cells such as imports).
3. **How** — the FloPy/Python call in backticks and the one to three arguments
   that matter here.

Keep routine cells to 1–3 sentences. Reserve longer prose for genuinely new
concepts. Do not describe every trivial one-line cell separately — introduce a
logical *step* (build a package, load results, make a plot), which may cover a
short run of cells.

## Voice

- **Imperative, second person, active voice** — direct instructions to the
  student:
  - ✅ "Create the discretization package with `flopy.mf6.ModflowGwfdis()`."
  - ✅ "Set the initial head (`strt`) to 320."
  - ❌ "We create the discretization package…" / "Here the model is loaded…"
- **This is a deliberate departure from the manuscript voice.** A paper prefers
  "an approach was developed"; a notebook tells a student what to do next, and
  the impersonal voice reads as detached narration in a class. Every other prose
  rule below applies unchanged.
- Short sentences. Prefer a period over a semicolon.
- Use imperative voice even in conceptual notebooks: frame the concept as
  something the student does or looks at ("Step through the simulation one time
  step at a time by calling `update()` until the end time is reached"), rather
  than as detached narration.
- **U.S. spelling** — color, center, meter, labeled, modeling, analyze. This
  covers figure labels and code comments, not only the markdown; a `colour` in a
  plotting cell reaches a legend.

## Prose rules

These are the faults that survive a technical review, in the order they are worth
looking for.

- **Do not evaluate a fact before giving it.** An opening clause that rates
  something the reader has not been told yet does no work the fact cannot do
  itself.

  | instead of | write |
  |---|---|
  | "This bears on the augmentation example: the well captures half its water from the stream." | "The well captures half its water from the stream, which is why the augmentation example cannot hold the gauge at its target." |

  The same fault appears as an evaluation bolted onto a finished sentence — "…,
  and that matters here", "…, and this is the practical value of an adjoint".
  Cover everything before the comma: if the sentence still carries what the
  student needs, the clause was rating rather than informing.

- **Do not announce an explanation; give it.** "There are two reasons for this",
  "The mechanism is subtle", "Read these numbers with care" — each is displaced
  by the sentence after it, which has to give the explanation anyway. A sentence
  that genuinely scaffolds a long passage is different; the test is deletion.

- **Cut the connective padding.** *Therefore*, *thus*, *in turn*, *as a result*,
  *it should be noted that*. A sentence that follows from the one before it does
  not need to say so.

- **Let the verb carry the action.** A verb turned into a noun needs a weak verb
  to prop it up.

  | instead of | write |
  |---|---|
  | "performs a calculation of specific discharge" | "calculates specific discharge" |
  | "provides a representation of the interface" | "represents the interface" |

- **Do not set one value against another.** *Against* makes a contest out of a
  comparison. Write *compared to*, or name the measurement: "check the adjoint
  with two model runs", not "against two model runs".

- **Describe the measurement, not the picture.** *Look similar*, *cannot be told
  apart*, *barely changes* report an impression a student can neither check nor
  use. Where a number exists, give it.

  | instead of | write |
  |---|---|
  | "the pattern barely changes between layers" | "layers 1 and 3 differ by 0.06 or less" |
  | "the curves cannot be told apart" | "the curves agree to 0.06 percent" |

  Appearance language earns its place only where the attribute is geometric —
  where a contour runs, which way a plume leans — and even there it is anchored
  to a value.

- **No italics for stress.** Italics ask the student to hear an emphasis the
  sentence should carry itself, and the fix is almost always a plainer word or a
  reordered sentence. Italics for a defined term or a publication title are
  fine.

- **A numeric claim has to be true as written.** A bound stated as "2.8 percent
  or less" is false when the largest value is 2.83, so round a bound *outward*.
  A maximum or a range means nothing without the set it was taken over: say
  "after the first year" or compute over everything. Recompute a bound from the
  array before it goes in the markdown — the error is invisible in the prose.

- **One name per thing.** "Backward sweep" and "backward solve" for the same
  operation make a student wonder what the difference is. Pick one and keep it,
  in the figure labels as well as the text.

## Plain language for beginners

- **Spell out every acronym on first use in a notebook**, then use the short
  form: "the Node Property Flow (**NPF**) package", "groundwater transport
  (**GWT**)", "the Buoyancy (**BUY**) package".
- **Teach each Python/FloPy idiom the first time it appears**, then just use it:
  - zero-based indexing — cell IDs are `(layer, row, column)` counting from 0.
  - `stress_period_data` as a dict keyed by the zero-based stress-period number.
  - list comprehension, `pathlib.Path`, f-strings — a half-sentence is enough.
  - units consistency — MODFLOW has no built-in units; inputs must share a
    consistent length and time unit (state which, e.g. feet and days).
- Before any list-based stress package (WEL, DRN, RIV, GHB, …), show one
  annotated example tuple so the field order is unambiguous:
  ```python
  # (layer, row, column, stage, cond, rbot)
  (0, 0, 0, 320.0, 1e5, 318.0)
  ```
- Bold a key term (`**like this**`) the first time you define it.

## Technical terms

The acronym and Python-idiom rules above apply just as much to the hydrology and
the numerics. A student who has not built a model before does not know what
transmissivity, a confined aquifer, or a fully penetrating well is, and a term
used before it is explained is a term the reader has to skip past.

- **Name the idea before you name the term.** Say what the thing does in a
  sentence of plain words, then give it its name. Keep the real term — students
  will meet it in the literature — but put it second.

  Before:

  > Use **reciprocity**: put the performance measure at each *well* rather than
  > at each observation point, and one backward solve returns that well's
  > response everywhere.

  After:

  > A pumping well and an observation point can be exchanged. The drawdown you
  > would measure at B while pumping at A is the same as the drawdown you would
  > measure at A if you pumped the same way at B instead. Groundwater flow is
  > symmetric in that sense, and the symmetry has a name: **reciprocity**.

- **Prefer the physical story to the formal statement.** "The lake surface is
  free to rise and fall, so pumping lowers the heads beneath it, the lake gives
  up water, its surface drops, and that drop slows the leakage" beats "the stage
  is a dependent variable, so the sensitivity is a total derivative rather than a
  partial one". Where the formal wording is worth having, put it after the
  picture, not instead of it.

- **Define a term where the notebook first leans on it**, not where it is most
  convenient. If the code prints `T` and `S`, the markdown above it says what
  transmissivity and storativity are.

- **Every notebook stands on its own.** A notebook may point at another for a
  fuller treatment, but it must not depend on that other notebook for a term it
  uses. Definitions travel with the notebook that needs them, even when that
  means saying the same thing in two places.

- **Re-read the back-references whenever a notebook moves.** "Again", "as
  before", and "as we saw above" silently break when sections are reordered or a
  notebook is split, and they leave a term looking defined when it never was.

## Structure of a notebook

- **Open** with a short "what this notebook covers" section: the goal in one or
  two sentences, and what the student will be able to do by the end. Keep any
  existing problem description, domain figure, and literature citation.
- Use a subheader for each major stage — build DIS, build NPF, define boundary
  conditions, write, run, post-process, plot. Any level (`##` or `###`) is fine;
  what matters is that a notebook picks one level for its stage headers and uses
  it consistently, under the top-level (`#`) title.
- **After a results plot, add a one-paragraph "What to look for"** that says how
  to read the figure and quotes the numbers it shows. This is where the
  measurement rule above bites hardest: the cell exists to give the student a
  value, not an impression.
- **Close** with a brief "Recap" listing what was built and shown.

## Figures

Notebook figures are teaching figures, and they are read on a projector. Follow
the conventions the manuscript figures use, since the same plots often end up in
a report:

- **Start the notebook with `%matplotlib inline`.** Without it only the first
  figure drawn inside a `flopy.plot.styles` context is rendered, and every later
  one is silently dropped.
- **Draw inside a `flopy.plot.styles` context** — `styles.USGSMap()` for maps,
  `styles.USGSPlot()` for everything else. The style supplies the fonts, tick
  geometry, and save settings; do not re-set them.
- **Multi-panel figures use `plt.subplot_mosaic` with `layout="constrained"`**,
  with named panels rather than an indexed array, so a panel can be added
  without renumbering.
- **Letter every panel** and say in the "What to look for" cell which letter
  carries which claim.
- **Axis labels and legends name the hydrologic quantity and its units**, not
  the array or the column the plotting code used.
- **Derive limits, ticks, and category lists from the constants that define
  them** rather than hardcoding them, so a figure follows the model when the
  model changes.

## Scaffolding — keep it lean

The audience is a live class, so keep the prose lecture-paced:

- **Drop the repeated `Shift-Tab` "see the optional variables" tips.** Mention
  once per notebook at most, if at all.
- **Keep only a few key reference links per notebook** — for example a single
  link to the MODFLOW 6 input/output docs and the FloPy docs near the start, or
  on the one package that is the notebook's focus. Do **not** attach a
  ReadTheDocs link to every package cell.
- Prefer explaining the idea in the notebook over sending the student to a link.

## Hard constraints

- **Never change code cells during a prose pass.** Edit and add **markdown**
  cells only. If a code cell's behavior is unclear, describe what it *does*; do
  not "fix" it here.
- **Do not invent numbers or facts.** Describe the values already in the code and
  their meaning; if you are unsure what a value represents, describe it
  generically rather than guessing. A number quoted in a "What to look for" cell
  comes from the notebook's own output.
- **Preserve technical accuracy.** These are authored by MODFLOW developers; keep
  existing correct terminology, citations, and figures intact.
- Keep notebooks valid JSON (edit via a notebook-aware tool, not raw text).
- **Paired helper modules follow `jdhughes-code-style`** — a one-line docstring
  saying what the function does, and short inline comments for the reasoning.
  The mechanism goes in the body, not in the docstring.

## Quick before / after

A bare plotting cell with no description:

```python
mm = flopy.plot.PlotMapView(model=gwf, layer=2, extent=gwf.modelgrid.extent)
cbv = mm.plot_array(hds)
q = mm.plot_vector(spd["qx"], spd["qy"])
mm.plot_bc("RIV", color="blue")
mm.plot_bc("WEL", plotAll=True)
```

Add a preceding markdown cell:

> #### Plot the results
>
> Map the simulated heads in the bottom layer with
> `flopy.plot.PlotMapView()`. Plot the head array with `.plot_array()`, the
> flow directions with `.plot_vector()`, and the well and river cells with
> `.plot_bc()`.

And, after the plot, a "What to look for":

> **What to look for.** Heads are highest near the river on the right and fall
> 12 ft toward the pumping well; the arrows show water moving from the river
> toward the well.
