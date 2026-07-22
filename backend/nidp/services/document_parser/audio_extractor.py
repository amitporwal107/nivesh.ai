"""Recover earnings-call content that was never published as text.

Many Indian issuers satisfy Regulation 30 by filing a one-page letter that says
"the audio recording of the conference call is available at <url>" and never
publish a transcript at all. The letter parses perfectly and carries no content:
pypdf, OCR, and vision all "succeed" on a page of letterhead, and the call itself
— the management commentary the corpus exists to answer questions about — is in
an mp3 no PDF tool can reach.

Worse, the letter mentions "earnings conference call", so the content classifier
types it `concall_transcript`. Measured on staging: 157 of 453 typed transcripts
(35%) contain no transcript markers. A user opening one gets a letterhead.

This module closes that gap generically — it keys off the *shape* of the
disclosure (audio wording + a media URL), never off any issuer, host or filename:

    letter PDF -> media URL -> download -> transcribe -> real transcript text

Graceful by contract, like `ocr_available()`: if docker or the whisper image is
absent, `audio_available()` is False, callers skip the path, and the document is
stored as the letter it is. Nothing breaks; the corpus is just no richer.

Self-hosted and offline by design: the image carries its weights, runs with
--network=none, and is CPU-capped so it cannot starve co-located Postgres. That
also means no API key, no per-call bill, and no silent 401 degradation.
"""
from __future__ import annotations

import contextlib
import fcntl
import io
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time

logger = logging.getLogger(__name__)

# Bounded: a 45-min call is ~5MB at the 16kbps/8kHz exchanges publish. 200MB is
# generous headroom while still refusing to stream something pathological.
_MAX_AUDIO_BYTES = int(os.environ.get("NIDP_MAX_AUDIO_BYTES", str(200 * 1024 * 1024)))
_TRANSCRIBE_TIMEOUT_S = int(os.environ.get("NIDP_TRANSCRIBE_TIMEOUT_S", "5400"))  # 1.5h
_WHISPER_IMAGE = os.environ.get("NIDP_WHISPER_IMAGE", "nidp-whisper:small")
# Root disk, NOT the NFS share: /mnt/nidp-nfs is where the staging Postgres data
# directory actually lives (via a symlink from /opt/nidp-staging/data/postgres),
# so every megabyte parked there competes with the database. Root has the room.
_WHISPER_TAR = os.environ.get("NIDP_WHISPER_TAR",
                              "/opt/nidp-staging/whisper/nidp-whisper-small.tar")
_WHISPER_CPUS = os.environ.get("NIDP_WHISPER_CPUS", "2")
# Hard memory ceiling per transcription. Measured ~1.4GB RSS for a 45-min call.
# The cap turns "the host OOMs" into "this container dies and the doc retries" —
# the kernel OOM-killer is not a scheduling strategy.
_WHISPER_MEM = os.environ.get("NIDP_WHISPER_MEM", "3g")
# System-wide concurrency gate. Transcriptions are spawned by MULTIPLE processes
# — the 15-min cron and every parser shard — so an in-process semaphore sees
# nothing. A file lock is the only thing they all share. Default 1: on 2026-07-17
# this VM was OOM-killed with unbounded 1.4GB/110%-CPU containers stacking up
# beside prod Postgres, taking SSH and the IDE down with it.
_TRANSCRIBE_LOCK = os.environ.get("NIDP_TRANSCRIBE_LOCK", "/var/tmp/nidp-transcribe.lock")
_LOCK_WAIT_S = int(os.environ.get("NIDP_TRANSCRIBE_LOCK_WAIT_S", "2700"))

_AUDIO_EXT = (".mp3", ".m4a", ".wav", ".aac", ".ogg", ".mp4", ".m4v")

# A URL anywhere in the letter text. Trailing punctuation is stripped by the
# caller — PDFs habitually glue a full stop or bracket onto the last character.
_URL_RE = re.compile(r"https?://[^\s<>\"')\]}]+", re.I)

# The disclosure's shape, not any issuer's wording. Both halves must be present:
# "audio/recording/replay" alone matches AGM notices; "conference call" alone
# matches the intimation filed days *before* the call, which has no media at all.
_AUDIO_WORDS = re.compile(r"\b(audio|recording|replay|webcast)\b", re.I)
_CALL_WORDS = re.compile(r"\b(earnings\s+call|conference\s+call|con[- ]?call|investor\s+call|"
                         r"analyst[s]?\s+(?:and\s+investors?\s+)?(?:meet|call))\b", re.I)


def audio_available() -> bool:
    """True when we can actually transcribe — docker plus the image or its tar.

    Mirrors `ocr_available()`: callers check this and skip rather than fail, so a
    VM without the image parses letters exactly as it does today.
    """
    if not shutil.which("docker"):
        return False
    if _image_present():
        return True
    return os.path.exists(_WHISPER_TAR)


def _image_present() -> bool:
    try:
        r = subprocess.run(["docker", "image", "inspect", _WHISPER_IMAGE],
                           capture_output=True, timeout=30)
        return r.returncode == 0
    except Exception:  # noqa: BLE001 — docker absent/hung is just "unavailable"
        return False


def looks_like_audio_disclosure(text: str) -> bool:
    """Is this the 'recording is available at <url>' letter?

    Requires audio wording AND call wording. Deliberately narrow: the cost of a
    false positive is a pointless download, and of a false negative just today's
    behaviour.
    """
    if not text:
        return False
    head = text[:4000]  # the claim is always in the subject/body, never page 12
    return bool(_AUDIO_WORDS.search(head) and _CALL_WORDS.search(head))


def find_media_urls(text: str, pdf_body: bytes | None = None) -> list[str]:
    """Media URLs from the letter — body text first, then link annotations.

    Both are needed: issuers variously print the URL, or hyperlink a phrase like
    "click here" with the target only in the PDF's annotation dictionary.
    Host-agnostic by design — every issuer self-hosts on its own domain.
    """
    found: list[str] = []
    for raw in _URL_RE.findall(text or ""):
        u = raw.rstrip(".,;:)]}’'\"")
        if _is_media(u):
            found.append(u)
    if pdf_body:
        found.extend(u for u in _annotation_urls(pdf_body) if _is_media(u))
    # dedupe, preserve order
    seen: set[str] = set()
    return [u for u in found if not (u in seen or seen.add(u))]


def _is_media(url: str) -> bool:
    path = url.split("?", 1)[0].split("#", 1)[0].lower()
    return path.endswith(_AUDIO_EXT)


def _annotation_urls(pdf_body: bytes) -> list[str]:
    """URI link annotations. Best-effort: a malformed annots dict must not fail
    the parse — we are already past a successful text extraction here."""
    out: list[str] = []
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(pdf_body))
        for page in reader.pages:
            for annot in (page.get("/Annots") or []):
                try:
                    obj = annot.get_object()
                    uri = (obj.get("/A") or {}).get("/URI")
                    if uri:
                        out.append(str(uri))
                except Exception:  # noqa: BLE001
                    continue
    except Exception as e:  # noqa: BLE001
        logger.debug("annotation scan failed: %s", e)
    return out


def _download(url: str, dest: str) -> int:
    """Fetch the media. Browser headers for the same reason the PDF downloader
    needs them — issuer CDNs and exchange hosts reject bare clients."""
    import requests  # local import: keeps the module importable without network deps
    headers = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
        "Accept": "*/*",
    }
    with requests.get(url, headers=headers, timeout=180, stream=True) as r:
        r.raise_for_status()
        declared = int(r.headers.get("content-length") or 0)
        if declared > _MAX_AUDIO_BYTES:
            raise ValueError(f"audio too large: {declared} bytes (cap {_MAX_AUDIO_BYTES})")
        size = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                size += len(chunk)
                if size > _MAX_AUDIO_BYTES:
                    raise ValueError(f"audio exceeded cap mid-stream ({_MAX_AUDIO_BYTES})")
                f.write(chunk)
    return size


@contextlib.contextmanager
def _transcribe_slot():
    """Serialise transcriptions across every process on this host.

    Blocking rather than skip-on-contention: a skipped audio letter would be
    stored as the letterhead it appears to be, silently recreating the 35%
    false-positive rate this path exists to remove. Waiting costs one of
    --concurrency workers; the rest keep parsing.

    Yields False on timeout so the caller leaves the document for a later run
    instead of finalising it as a letter.
    """
    fd = os.open(_TRANSCRIBE_LOCK, os.O_CREAT | os.O_RDWR, 0o666)
    acquired = False
    try:
        deadline = time.time() + _LOCK_WAIT_S
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError:
                if time.time() >= deadline:
                    logger.warning("transcribe slot busy >%ss — deferring this doc", _LOCK_WAIT_S)
                    break
                time.sleep(5)
        yield acquired
    finally:
        if acquired:
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def transcribe_url(url: str) -> str | None:
    """Download and transcribe. Returns None on any failure — never raises.

    The document is still storable as the letter it is; a missing transcript is
    a smaller loss than a failed parse.
    """
    if not audio_available():
        logger.warning("transcribe skipped: docker/whisper image unavailable")
        return None
    if not _image_present() and not _load_image():
        return None

    with tempfile.TemporaryDirectory() as work:
        audio = os.path.join(work, "call.mp3")
        out = os.path.join(work, "call.txt")
        try:
            size = _download(url, audio)
            logger.info("audio downloaded %s bytes from %s", size, url[:90])
        except Exception as e:  # noqa: BLE001
            logger.warning("audio download failed %s: %s", url[:90], e)
            return None

        os.chmod(work, 0o777)  # the container runs as its own uid
        with _transcribe_slot() as got_slot:
            if not got_slot:
                return None  # host already transcribing; leave this doc pending
            try:
                r = subprocess.run(
                    ["docker", "run", "--rm", "--network=none",
                     f"--cpus={_WHISPER_CPUS}", f"--memory={_WHISPER_MEM}",
                     "-v", f"{work}:/work", _WHISPER_IMAGE, "/work/call.mp3", "/work/call.txt"],
                    capture_output=True, timeout=_TRANSCRIBE_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                logger.warning("transcription timed out after %ss: %s", _TRANSCRIBE_TIMEOUT_S, url[:90])
                return None
            if r.returncode != 0:
                logger.warning("transcriber exited %s: %s", r.returncode, r.stderr[-300:])
                return None
        try:
            text = open(out, encoding="utf-8").read().strip()
        except OSError as e:
            logger.warning("transcript unreadable: %s", e)
            return None

    if len(text) < 500:
        # A real call is thousands of words. Anything shorter means the audio was
        # silence, a jingle, or a hold-music placeholder — do not pass it off as
        # a transcript, that is how the 35% false-positive rate happened.
        logger.warning("transcript too short (%d chars) — discarding: %s", len(text), url[:90])
        return None
    logger.info("transcribed %d chars from %s", len(text), url[:90])
    return text


def _load_image() -> bool:
    """Load the image from its tar. Kept on shared storage rather than the root
    filesystem: nidp-stack-vm runs at ~90% disk and co-hosts prod Postgres."""
    try:
        logger.info("loading whisper image from %s", _WHISPER_TAR)
        r = subprocess.run(["docker", "load", "-i", _WHISPER_TAR],
                           capture_output=True, timeout=600)
        if r.returncode != 0:
            logger.warning("docker load failed: %s", r.stderr[-300:])
            return False
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("docker load error: %s", e)
        return False
