# SpiderVIP-Firmware-Patch

One-click patcher for SpiderVIP satellite-receiver firmware. When the vendor
releases a new official firmware, you flash it to the receiver, then run this
tool once to re-apply your custom improvements on top of it.

The first, always-applied improvement marks the version shown in the receiver's
settings/About menu with the word `patch` (for example `1.00.93` becomes
`1.00.93 patch`) so a custom build is instantly recognisable.

## Status

- Version-marking, image analysis and the patch pipeline are implemented and
  tested (against an unpacked root filesystem).
- The binary `.mupg` container (un)packer is **not finalised yet**: `.mupg` is
  the proprietary DefineOS firmware-package format, and a mis-repacked image can
  brick a receiver. The tool therefore refuses to repack a real `.mupg` until
  its exact layout is reversed from a sample and a byte-exact round-trip is
  validated. See "Providing a sample" below.

## Install

```bash
pip install -e ".[dev]"
```

No runtime dependencies (standard library only). `inspect` optionally uses the
external `file` and `binwalk` tools when they are installed.

## Usage

```bash
# Analyze a firmware image (use this on a real .mupg to reverse the format)
mupg-patch inspect SPIDER-VIP_v1.00.93_20260507.mupg

# One-click patch (works today on an unpacked root filesystem; on .mupg once
# the container handler is validated)
mupg-patch patch --in <image-or-rootfs-dir> --out <patched-image>

# Mark the version directly in an already-unpacked root filesystem
mupg-patch mark-version --rootfs <rootfs-dir> --marker patch
```

## How the version marker works

The receiver's About/settings version is read from a text file inside the root
filesystem (DefineOS/Enigma2 images use an `image-version`/`imageversion`-style
file). The marker appends the word after the version number, idempotently, so
running the patch twice never produces `1.00.93 patch patch`. The exact target
file is confirmed from a sample image (see `mupgpatch/versionmark.py` →
`VERSION_FILE_CANDIDATES`).

## Providing a sample (to finalise `.mupg` support)

`.mupg` is proprietary, so the unpack/repack handler must be reversed from a
real image. Provide **one** official sample (e.g.
`SPIDER-VIP_v1.00.92_20260507.mupg`) and the tool can be completed and validated:

```bash
mupg-patch inspect SPIDER-VIP_v1.00.92_20260507.mupg
file       SPIDER-VIP_v1.00.92_20260507.mupg
binwalk -Me SPIDER-VIP_v1.00.92_20260507.mupg   # if binwalk is available
```

The handler will only be trusted after an unmodified sample can be unpacked and
repacked into a byte-exact / device-valid image.

## Docs

- Persian workflow & format notes: [`docs/firmware-patch-fa.md`](docs/firmware-patch-fa.md)

## Layout

```
mupgpatch/
  versionmark.py   # idempotent version -> "version patch" marker (core feature)
  inspect.py       # image analyzer (magic/entropy/version strings + file/binwalk)
  container.py     # DirectoryImage (works now) + MupgContainer (needs a sample)
  patcher.py       # one-click pipeline: unpack -> improvements -> repack
  cli.py           # `mupg-patch` command
tests/             # pytest suite
```

## Development

```bash
pip install -e ".[dev]"
pytest -q
```
