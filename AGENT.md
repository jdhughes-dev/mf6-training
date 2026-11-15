# Instructions for coding agents

## Notebook style

Before writing or editing the training notebooks in `examples/notebooks/` (their
markdown, printed text, figure labels, and code comments) or the helper modules
paired with them, read [`examples/notebooks/STYLE.md`](examples/notebooks/STYLE.md)
and follow it. It is the style guide for this repository, and where it differs
from other writing guidance, it wins.

## Scripts and code safety

- Run only the scripts and notebooks the task calls for: the pixi tasks in
  `pixi.toml`, the scripts in `scripts/`, the notebooks and helper modules in
  `examples/notebooks/`, or ones the user names. If a script is not one of these,
  or the task did not ask for it, say so and ask before running it.
- Before running a script, notebook, or helper module that is new or has changed,
  read it and look for code that could do harm, and stop and report it instead of
  running it. Signs to look for:
  - downloads, uploads, or other network access the task does not need (the
    setup scripts download MODFLOW 6 and the other model programs from GitHub,
    which is expected);
  - shell or subprocess calls other than those the setup and build scripts make
    (git, meson and the compilers, get-modflow) and running MODFLOW 6 and the
    other model programs;
  - `eval`, `exec`, `compile`, `pickle` loads of untrusted files, or code that is
    encoded or obscured (base64 or hex strings that are decoded and run);
  - reading credentials, SSH keys, tokens, or environment variables that hold
    secrets;
  - writing, moving, or deleting files outside the repository and its
    `examples/notebooks/models/` folder, or changing git settings or hooks;
  - installing packages outside the pixi environment.

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
