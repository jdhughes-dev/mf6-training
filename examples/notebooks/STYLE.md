# Notebook description style guide

How to write the markdown descriptions that accompany code cells in the
training notebooks under `examples/notebooks/`. The goal is a single, consistent
voice that a student with **no-to-moderate Python, FloPy, and MODFLOW 6
experience** can follow in a live class and review on their own afterward.

The two reference notebooks are
[`flopy-intro-gwf-only.ipynb`](flopy-intro-gwf-only.ipynb) (a guided model
build) and [`modflow-api-A.ipynb`](modflow-api-A.ipynb) (a concept walk-through).
When in doubt, match them.

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
  student, the same voice used throughout `flopy-intro-gwf-only.ipynb`:
  - ✅ "Create the discretization package with `flopy.mf6.ModflowGwfdis()`."
  - ✅ "Set the initial head (`strt`) to 320."
  - ✅ "Load the heads with `gwf.output.head()` and name them `hds`."
  - ❌ "We create the discretization package…" / "Here the model is loaded…"
- Short sentences. Prefer a period over a semicolon.
- Use imperative voice even in conceptual notebooks: frame the concept as
  something the student does or looks at ("Step through the simulation one time
  step at a time by calling `update()` until the end time is reached"), rather
  than as detached narration.

## Plain language for beginners

- **Spell out every acronym on first use in a notebook**, then use the short
  form: "the Node Property Flow (**NPF**) package", "groundwater transport
  (**GWT**)", "particle-tracking (**PRT**)".
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

## Structure of a notebook

- **Open** with a short "what this notebook covers" section: the goal in one or
  two sentences, and what the student will be able to do by the end. Keep any
  existing problem description, domain figure, and literature citation.
- Use `####` subheaders for each major stage — build DIS, build NPF, define
  boundary conditions, write, run, post-process, plot.
- **After a results plot, add a one-paragraph "What to look for"** so students
  know how to read it (what the colors/contours/lines mean, what the expected
  or interesting behavior is).
- **Close** with a brief "Recap" listing what was built and shown.

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

- **Never change code cells.** Edit and add **markdown** cells only. If a code
  cell's behavior is unclear, describe what it *does*; do not "fix" it here.
- **Do not invent numbers or facts.** Describe the values already in the code
  and their meaning; if you are unsure what a value represents, describe it
  generically rather than guessing.
- **Preserve technical accuracy.** These are authored by MODFLOW developers;
  keep existing correct terminology, citations, and figures intact.
- Keep notebooks valid JSON (edit via a notebook-aware tool, not raw text).

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

> **What to look for.** Heads are highest near the river on the right and draw
> down toward the pumping well; the arrows show water moving from the river
> toward the well.
