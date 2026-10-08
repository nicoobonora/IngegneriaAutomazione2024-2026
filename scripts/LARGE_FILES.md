# Large files on push

Requires Git and Python 3. The installed pre-push hook runs on ordinary `git push`.
Files at or above 100,000,000 bytes become binary parts of at most 90,000,000 bytes,
with a JSON manifest and SHA-256 checksums. PDFs must be restored before opening.
Originals remain on disk and are ignored by Git. Parts and original removals are staged.

The first push that creates parts stops so you can review the staged changes.
A push hook cannot replace commits already selected by Git. Commit the parts and
remove the large originals from all outgoing commits before retrying. For this
repository's single unpushed initial commit, review then run:

    git commit --amend --no-edit
    git push

Do not amend shared commits without coordinating with collaborators. The script
never rewrites history or pushes automatically. It blocks pushes while any blob
at or above the limit remains reachable from a pushed tip (including old history).

To prepare without pushing:

    python3 scripts/split_large_files.py prepare

To reconstruct in another clone:

    python3 scripts/split_large_files.py restore "path/to/file.pdf.parts"

Use `--output "another/path.pdf"` to choose a destination. Existing files are never
overwritten; each part and the complete reconstructed file are verified.

Only tracked, unchanged files are prepared. Staged changes must first be committed
or unstaged. To update a split original, remove its old tracked `.parts` folder,
force-add and commit the changed original, then prepare and amend that local commit.
Do not push the intermediate commit with the oversized original.

Hooks are local: on a new clone, install `pre-push` into `.git/hooks/pre-push` and
make it executable. Keep the Python script at `scripts/split_large_files.py`.
