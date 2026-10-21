# Provenance and licensing

## Upstream

- Project: `ffmpeg_pipeline`
- Upstream repository: <https://github.com/yoshito-n-students/ffmpeg_pipeline>
- Upstream author / copyright holder: **Yoshito Okada**, Tohoku University
  (`okada@tohoku.ac.jp`)
- License: **MIT** (declared per-package in `package.xml` since the upstream
  tree carries no root `LICENSE` file; this fork adds one)
- Forked at commit: `5ffbabbfeba565f200ae03187052ec380f2536ca` (branch `jazzy`,
  2025-11-28)

## This fork

- Fork maintainer: **MichaelYWNA** (温慕晨昂) — <https://github.com/MichaelYWNA>
- License of this fork: MIT, same terms, both copyright lines retained in
  [`LICENSE`](../LICENSE) as required by the MIT conditions.

## What is upstream code and what is mine

Everything under `ffmpeg_cpp/`, `ffmpeg_controllers/`, `ffmpeg_hardware/`,
`ffmpeg_image_transport/`, `ffmpeg_pipeline/`, `ffmpeg_pipeline_msgs/` and the
pre-existing directories of `ffmpeg_pipeline_examples/` is **upstream code by
Yoshito Okada**, carried over unmodified unless a commit of mine says
otherwise. The `CHANGELOG.rst` files are upstream release history and are kept
as-is.

My own work in this fork is limited to what my commits actually contain; see
`git log --author=MichaelYWNA --stat`. Anything I add lives in new files or in
explicitly documented edits, and each of my commits states which upstream
behaviour it changes and why.

## Why the maintainer field changed

`<maintainer>` means "who answers for *this* repository". In a fork that is the
fork owner, so `package.xml` lists MichaelYWNA as maintainer while
`<author>` keeps the original authorship visible. The MIT copyright notice is
never removed.
