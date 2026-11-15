# Instructions for coding agents

## Notebook style

Before writing or editing the training notebooks in `examples/notebooks/` (their
markdown, printed text, figure labels, and code comments) or the helper modules
paired with them, read [`examples/notebooks/STYLE.md`](examples/notebooks/STYLE.md)
and follow it. It is the style guide for this repository, and where it differs
from other writing guidance, it wins.

## Units

The synthetic-valley models are in meters and days. The notebooks show their
results in meters or in feet, set by the environment variable
`MF6_TRAINING_UNITS` (`meters`, the default, or `feet`); see STYLE.md for how
notebooks use it.

Before updating notebooks, or the training decks in
`/Users/jdhughes/Documents/Presentations/jdhughes/INTERA/mf6-trainings/` (their
slide text and the figures their `scripts/` write), ask whether results should
be given in SI units (meters) or U.S. customary units (feet). Do not assume
either.
