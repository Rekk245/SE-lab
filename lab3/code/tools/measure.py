"""Count physical, nonblank and noncomment source lines transparently."""

import io
import json
import pathlib
import tokenize


def count(path):
    "Count code-bearing lines, excluding comments and standalone"
    "docstrings."
    text = path.read_text(encoding="utf-8")
    excluded = set()
    previous = tokenize.INDENT
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        if token.type == tokenize.COMMENT:
            if not text.splitlines()[token.start[0] - 1][
                : token.start[1]
            ].strip():
                excluded.add(token.start[0])
        elif token.type == tokenize.STRING and previous in (
            tokenize.INDENT,
            tokenize.NEWLINE,
            tokenize.DEDENT,
        ):
            excluded.update(range(token.start[0], token.end[0] + 1))
        if token.type not in (tokenize.ENCODING, tokenize.NL, tokenize.COMMENT):
            previous = token.type
    lines = text.splitlines()
    return dict(
        physical=len(lines),
        nonblank=sum(bool(line.strip()) for line in lines),
        code_lines=sum(
            bool(line.strip()) and index not in excluded
            for index, line in enumerate(lines, 1)
        ),
    )


def main():
    "Report application and test counts separately; no GUI generator"
    "exists."
    root = pathlib.Path(__file__).resolve().parents[1]
    files = {
        str(path.relative_to(root)).replace("\\", "/"): count(path)
        for path in sorted((root / "shared_ledger").glob("*.py"))
    }
    totals = {
        key: sum(row[key] for row in files.values())
        for key in ("physical", "nonblank", "code_lines")
    }
    tests = sum(
        count(path)["physical"] for path in (root / "tests").glob("*.py")
    )
    print(
        json.dumps(
            dict(
                scope="shared_ledger/*.py only",
                files=files,
                total=totals,
                tests_physical=tests,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
