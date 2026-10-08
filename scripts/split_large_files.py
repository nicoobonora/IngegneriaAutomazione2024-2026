#!/usr/bin/env python3
"""Split large tracked files before pushing; restore with integrity verification."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

LIMIT = 100_000_000
CHUNK = 90_000_000


def git(*args, data=None):
    return subprocess.check_output(['git', *args], input=data)


def split_file(source, destination, chunk_size=CHUNK):
    source, destination = Path(source), Path(destination)
    if destination.exists():
        raise RuntimeError(f'Refusing to overwrite {destination}')
    temporary = Path(tempfile.mkdtemp(prefix='.splitting-', dir=destination.parent))
    digest = hashlib.sha256()
    parts = []
    size = 0
    try:
        with source.open('rb') as src:
            while True:
                block = src.read(chunk_size)
                if not block:
                    break
                name = f'part-{len(parts) + 1:06d}'
                (temporary / name).write_bytes(block)
                digest.update(block)
                size += len(block)
                parts.append({'name': name, 'size': len(block), 'sha256': hashlib.sha256(block).hexdigest()})
        manifest = {'version': 1, 'filename': source.name, 'size': size, 'sha256': digest.hexdigest(), 'parts': parts}
        (temporary / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        temporary.rename(destination)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def restore(folder, output=None):
    folder = Path(folder)
    manifest = json.loads((folder / 'manifest.json').read_text())
    name = manifest['filename']
    if Path(name).name != name or name in ('.', '..'):
        raise RuntimeError('Unsafe filename in manifest')
    output = Path(output) if output else folder.parent / name
    if output.exists():
        raise RuntimeError(f'Refusing to overwrite {output}')
    digest = hashlib.sha256()
    size = 0
    fd, temporary = tempfile.mkstemp(prefix='.restoring-', dir=output.parent)
    try:
        with os.fdopen(fd, 'wb') as dst:
            for part in manifest['parts']:
                if Path(part['name']).name != part['name']:
                    raise RuntimeError('Unsafe part path')
                block = (folder / part['name']).read_bytes()
                if len(block) != part['size'] or hashlib.sha256(block).hexdigest() != part['sha256']:
                    raise RuntimeError(f"Corrupt part: {part['name']}")
                dst.write(block)
                digest.update(block)
                size += len(block)
        if size != manifest['size'] or digest.hexdigest() != manifest['sha256']:
            raise RuntimeError('Reconstructed file failed verification')
        # Hard linking prevents overwriting a file created concurrently.
        os.link(temporary, output)
    finally:
        os.unlink(temporary)
    print(f'Restored {output}')


def prepare():
    root = Path(os.fsdecode(git('rev-parse', '--show-toplevel')).strip())
    os.chdir(root)
    if git('diff', '--cached', '--name-only'):
        raise RuntimeError('Commit or unstage your staged changes before preparing large files.')
    candidates = []
    for raw in git('ls-files', '-z').split(b'\0'):
        if not raw:
            continue
        path = Path(os.fsdecode(raw))
        if not path.is_symlink() and path.is_file() and path.stat().st_size >= LIMIT:
            if git('diff', '--name-only', '--', str(path)):
                raise RuntimeError(f'Commit or stash changes to {path} first.')
            candidates.append(path)
    for path in candidates:
        if Path(str(path) + '.parts').exists():
            raise RuntimeError(f'Existing parts for {path}: remove or move them before regenerating.')
    for path in candidates:
        folder = Path(str(path) + '.parts')
        split_file(path, folder)
        # Adjacent ignore rules apply only to this original, including special characters.
        escaped = ''.join('\\' + c if c in '\\*?[]#! ' else c for c in path.name)
        ignore = path.parent / '.gitignore'
        existing = ignore.read_text() if ignore.exists() else ''
        rule = '/' + escaped
        if rule not in existing.splitlines():
            ignore.write_text(existing + ('' if not existing or existing.endswith('\n') else '\n') + rule + '\n')
        git('rm', '--cached', '--', str(path))
        git('add', '--', str(folder), str(ignore))
        print(f'Split {path} into {folder}; original retained locally.')
    return bool(candidates)


def pre_push():
    updates = [line.split() for line in sys.stdin.read().splitlines() if line.strip()]
    if prepare():
        raise RuntimeError('Parts are staged for review. Commit them, remove oversized originals from outgoing history, then push again. For a single unpushed initial commit, use git commit --amend --no-edit after review.')
    tips = [row[1] for row in updates if set(row[1]) != {'0'}]
    if not tips:
        return
    # Check all reachable history: a deletion commit does not remove old blobs.
    objects = git('rev-list', '--objects', '--no-object-names', *tips)
    info = git('cat-file', '--batch-check=%(objectname) %(objecttype) %(objectsize)', data=objects)
    bad = [line for line in info.decode().splitlines() if line.split()[1] == 'blob' and int(line.split()[2]) >= LIMIT]
    if bad:
        raise RuntimeError(f'{len(bad)} oversized blob(s) remain in outgoing history. Rewrite the affected local commits before pushing. No history was changed automatically.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('prepare')
    hook = sub.add_parser('pre-push')
    hook.add_argument('remote', nargs='?')
    hook.add_argument('url', nargs='?')
    p = sub.add_parser('restore')
    p.add_argument('folder')
    p.add_argument('--output')
    args = parser.parse_args()
    if args.command == 'restore':
        restore(args.folder, args.output)
    elif args.command == 'prepare':
        prepare()
    else:
        pre_push()


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f'Large-file check: {exc}', file=sys.stderr)
        sys.exit(1)
