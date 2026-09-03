#!/usr/bin/env python3
"""Set one key in one table of a study TOML, in place.

Exists so an unattended run records its own parameter changes as commands
rather than as edits somebody has to reconstruct afterwards.
"""
import pathlib, re, sys

def main(path, table, key, value):
    p = pathlib.Path(path); text = p.read_text()
    marker = f"[{table}]"
    if marker not in text:
        raise SystemExit(f"{path}: no [{table}] table")
    head, tail = text[:text.index(marker)], text[text.index(marker):]
    # stop at the next table so a key present in two tables is not confused
    nxt = re.search(r"(?m)^\[", tail[len(marker):])
    body, rest = (tail[:len(marker) + nxt.start()], tail[len(marker) + nxt.start():]) if nxt else (tail, "")
    if re.search(rf"(?m)^{re.escape(key)}\s*=", body):
        body = re.sub(rf"(?m)^{re.escape(key)}\s*=.*$", f"{key} = {value}", body, count=1)
    else:
        body = body.rstrip("\n") + f"\n{key} = {value}\n\n"
    p.write_text(head + body + rest)
    print(f"{path}: [{table}] {key} = {value}")

if __name__ == "__main__":
    main(*sys.argv[1:5])
