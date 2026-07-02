# Contributing

Thanks for contributing to the MODFLOW 6 training materials. This page covers
the tooling that runs when you make a commit. See the
[README](README.md) for how to install pixi and the environment.

## Pre-commit hook

This repo uses a [pre-commit](https://pre-commit.com) hook that, on every
commit, runs three tools against the staged Python scripts and the notebooks
under `examples/notebooks/`:

1. **nbstripout** — clears notebook outputs and execution counts (notebooks only).
2. **codespell** — spell-checks and auto-corrects typos (config in `.codespellrc`).
3. **ruff** — applies lint fixes and formatting (config in `ruff.toml`).

Install it once per clone:

```bash
pixi run pre-commit-install
```

The hooks run in pre-commit's own managed tool environments (not the pixi
environment), so `git commit` works from any Git client — VS Code, the CLI, etc.
— without the pixi environment activated. Tool versions are pinned in
`.pre-commit-config.yaml` (kept in sync with `pixi.lock`); bump them with
`pixi run pre-commit autoupdate`.

To run the hooks against every file (not just staged changes):

```bash
pixi run pre-commit-run
```

CI runs the same hooks on every push and pull request, so committing with the
hook installed keeps notebooks clean and code consistently formatted.
