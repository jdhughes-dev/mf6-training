#!/usr/bin/env python
"""Generate student notebooks: copies of the example notebooks with the solutions removed.

A student notebook is the hands-on version of an example notebook. The prose, the
figures, and the scaffolding are all still there; the code the student is meant
to write is not.

Which code that is comes from markers in the notebook itself. A line

    # exercise: create the DIS package (3 layers, 21 rows, 20 columns)

marks the start of a solution. Everything from the next line to the end of the
cell, or to a line

    # end exercise

is removed and replaced with a "your code here" placeholder. The marker line
itself stays, so the prompt after the colon is the instruction the student sees.
Use the end marker when only part of a cell is the exercise - the rest of the
cell (a fiddly legend, say) is then handed to the student intact.

Outputs are cleared so a saved figure cannot give the answer away.

The generated notebooks go in a directory beside examples/notebooks/, not
inside it, so that the relative paths in the notebooks still resolve: several
of them read ../data/..., which would need a different number of levels from a
nested directory. Any paired helper module a generated notebook imports is
copied along with it, for the same reason.

    pixi run student-notebooks                      # every marked notebook
    pixi run student-notebooks examples/notebooks/flopy-intro-gwf-only-a.ipynb
    pixi run student-notebooks --output-dir /tmp/students
    python scripts/make_student_notebooks.py --check   # validate, write nothing
"""

import argparse
import ast
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

NOTEBOOK_DIR = Path("examples/notebooks")
DEFAULT_OUTPUT_DIR = NOTEBOOK_DIR.parent / "notebooks-students"

START = re.compile(r"^(\s*)#\s*exercise:\s*(\S.*)$")
END = re.compile(r"^\s*#\s*end exercise\s*$")
PLACEHOLDER = "# your code here"

README_NAME = "README.md"
README = """# Student notebooks

**These notebooks are generated. Do not edit them here — your changes will be
overwritten.**

Each one is a copy of the matching notebook in [`../notebooks`](../notebooks)
with the solutions removed: the prose, the figures, and the scaffolding are all
still there, and the code you are meant to write has been replaced by a prompt
and a `# your code here` placeholder.

```python
# exercise: create the DIS package (3 layers, 21 rows, 20 columns, 500 ft cells)
# your code here
```

Write your code under the prompt and run the cell. The complete notebook next
door is the answer key.

This directory is rebuilt by a pre-commit hook whenever a notebook changes, so
it stays in step with `../notebooks`. To rebuild it yourself:

```shell
pixi run student-notebooks
```

**Your work is safe.** A notebook you have started filling in has uncommitted
changes, and rebuilding skips those and says so, rather than overwriting them.
Commit or discard your changes when you want a fresh copy of that notebook. If
you would rather keep the originals pristine, work on a copy.

That is also where to fix anything wrong here — edit the notebook in
`../notebooks` and regenerate. The `# exercise:` markers in those notebooks are
what decides which code is removed; see
[`../notebooks/README.md`](../notebooks/README.md) for how they work.

The `.py` files beside these notebooks are copies of the paired helper modules
the notebooks import, and are generated too.

## Notebooks in this directory

"""


def blank_source(source: list[str]) -> tuple[list[str], int]:
    """Replace each marked solution in one cell's source with a placeholder.

    Returns the new source lines and the number of exercises found.
    """
    out: list[str] = []
    i = 0
    found = 0
    while i < len(source):
        line = source[i]
        match = START.match(line.rstrip("\n"))
        if match is None:
            out.append(line)
            i += 1
            continue

        indent = match.group(1)
        out.append(line)
        i += 1

        # drop the solution, up to the end marker or the end of the cell
        while i < len(source) and END.match(source[i].rstrip("\n")) is None:
            i += 1
        if i < len(source):
            i += 1  # the end marker itself is not shown to the student
        out.append(f"{indent}{PLACEHOLDER}\n")
        found += 1

        # keep one blank line between the placeholder and any code that follows
        if i < len(source) and source[i].strip():
            out.append("\n")
    return out, found


def check_blanked(source: list[str], path: Path, index: int) -> bool:
    """Warn if removing a solution left the cell unparsable.

    Code after an exercise must not sit inside a block the solution opened,
    or the student is handed an orphaned, indented fragment. Put the exercise
    at the end of its block to avoid it. Returns False when the cell is left
    unparsable.
    """
    text = strip_magics(source)
    try:
        compile(text, str(path), "exec")
    except SyntaxError as exc:
        print(
            f"[student-notebooks] ERROR {path} cell {index}: blanking the exercise "
            f"leaves invalid Python ({exc.msg}, line {exc.lineno}). Move the "
            f"exercise to the end of its block.",
            file=sys.stderr,
        )
        return False
    return True


def strip_magics(source: list[str]) -> str:
    """Cell source as Python, with IPython magic and shell lines commented out.

    Line numbers are preserved so a reported syntax error still points at the
    right line.
    """
    lines = []
    for line in source:
        stripped = line.lstrip()
        if stripped.startswith(("%", "!")):
            lines.append("#" + line[1:])
        else:
            lines.append(line)
    return "".join(lines)


def imported_modules(text: str) -> set[str]:
    """Top-level module names imported by one block of Python source."""
    names: set[str] = set()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return names
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def local_dependencies(nb: dict) -> set[str]:
    """Paired helper modules a notebook imports, following their imports too."""
    pending: set[str] = set()
    for cell in nb["cells"]:
        if cell["cell_type"] != "code":
            continue
        pending |= imported_modules(strip_magics(cell["source"]))

    found: set[str] = set()
    while pending:
        name = pending.pop()
        module = NOTEBOOK_DIR / f"{name}.py"
        if name in found or not module.is_file():
            continue
        found.add(name)
        pending |= imported_modules(module.read_text())
    return found


def has_local_changes(path: Path) -> bool:
    """Whether a tracked file differs from HEAD, staged or not.

    Students work in the generated directory, so overwriting a notebook they
    have started filling in would throw their work away. A file that still
    matches HEAD is pristine and safe to rebuild; one that does not is left
    alone. Anything git cannot answer for - an untracked file, no repository -
    counts as pristine, since there is no work recorded to lose.
    """
    if not path.is_file():
        return False
    try:
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", str(path)],
            capture_output=True,
            check=False,
        )
        if tracked.returncode != 0:
            return False
        diff = subprocess.run(
            ["git", "diff", "--quiet", "HEAD", "--", str(path)],
            capture_output=True,
            check=False,
        )
    except OSError:
        return False
    return diff.returncode == 1


def make_student_notebook(
    path: Path, output_dir: Path, check: bool
) -> tuple[int, set[str], bool]:
    """Write the student version of one notebook, or with check just validate it.

    Returns the exercise count, the helper modules the notebook needs, and
    whether every blanked cell is still valid Python.
    """
    nb = json.loads(path.read_text())
    total = 0
    ok = True
    for index, cell in enumerate(nb["cells"]):
        if cell["cell_type"] != "code":
            continue
        cell["source"], found = blank_source(cell["source"])
        if found:
            ok &= check_blanked(cell["source"], path, index)
        total += found
        cell["outputs"] = []
        cell["execution_count"] = None

    if total == 0 or check:
        return total, set(), ok

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / path.name
    if has_local_changes(out_path):
        print(
            f"[student-notebooks] SKIPPED {out_path}: it has uncommitted changes, "
            f"which look like work in progress. Commit or discard them to let it "
            f"be rebuilt from {path}.",
            file=sys.stderr,
        )
        return total, local_dependencies(nb), ok
    out_path.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n")
    return total, local_dependencies(nb), ok


def write_readme(output_dir: Path, entries: list[tuple[str, int]]) -> None:
    """Write the README explaining that everything here is generated."""
    lines = [README]
    for name, count in entries:
        lines.append(
            f"- [`{name}`]({name}) — {count} exercise{'s' if count != 1 else ''}, "
            f"generated from [`../notebooks/{name}`](../notebooks/{name})\n"
        )
    (output_dir / README_NAME).write_text("".join(lines))


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "notebooks",
        nargs="*",
        type=Path,
        help=f"notebooks to convert (default: every marked notebook in {NOTEBOOK_DIR})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"where to write the student notebooks (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="only verify that every marked notebook blanks to valid Python; "
        "write nothing. Used by the pre-commit hook.",
    )
    args = parser.parse_args(argv)

    given = bool(args.notebooks)
    paths = args.notebooks or sorted(NOTEBOOK_DIR.glob("*.ipynb"))
    missing = [p for p in paths if not p.is_file()]
    if missing:
        sys.exit(
            f"[student-notebooks] no such notebook: {', '.join(map(str, missing))}"
        )

    entries: list[tuple[str, int]] = []
    helpers: set[str] = set()
    problems = 0
    for path in paths:
        count, needed, ok = make_student_notebook(path, args.output_dir, args.check)
        problems += not ok
        if count:
            entries.append((path.name, count))
            helpers |= needed
            if not args.check:
                print(
                    f"[student-notebooks] {args.output_dir / path.name}: "
                    f"{count} exercise{'s' if count != 1 else ''}"
                )
        elif given and not args.check:
            # only worth reporting when the notebook was asked for by name
            print(f"[student-notebooks] {path}: no exercise markers, skipped")

    if problems:
        sys.exit(
            f"[student-notebooks] {problems} notebook{'s' if problems != 1 else ''} "
            f"would not blank cleanly"
        )

    if args.check:
        return

    if not entries:
        # being handed only unmarked notebooks is fine; finding none at all is not
        if given:
            return
        sys.exit("[student-notebooks] no notebooks contained '# exercise:' markers")

    # the notebooks import these by name, so they have to sit beside them
    for name in sorted(helpers):
        shutil.copy2(NOTEBOOK_DIR / f"{name}.py", args.output_dir / f"{name}.py")
        print(f"[student-notebooks] {args.output_dir / f'{name}.py'}: helper module")

    write_readme(args.output_dir, entries)
    print(
        f"[student-notebooks] wrote {len(entries)} "
        f"notebook{'s' if len(entries) != 1 else ''} and {README_NAME} "
        f"to {args.output_dir}"
    )


if __name__ == "__main__":
    main(sys.argv[1:])
