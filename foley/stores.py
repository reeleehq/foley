"""dol-backed storage for foley: content-addressed bytes + a metadata store.

This module provides the two persistence surfaces the whole façade stands on and
the single gate that decides whether a sound is held *by value* or *by reference*:

    * a **content-addressed byte store** — ``Mapping[content_key -> bytes]``,
      keyed by the sha256 hex digest of the bytes (dedup + immutability),
    * a **metadata store** — ``Mapping[sound_id -> SoundRecord]`` (JSON on disk),
    * :func:`store_sound` — the by-value vs by-reference gate, driven by
      ``LicenseRecord.cache_bytes_ok``.

Both stores are plain ``MutableMapping`` objects built from ``dol``. Local disk is
the default (``dol.Files`` / ``dol.JsonFiles``); moving to the cloud is a **store
injection** — pass any ``dol`` Mapping (e.g. an S3-backed store) for ``sounds``
and an S3/Postgres Mapping for ``meta`` — never a change to business logic.
Content keys make local↔cloud copies idempotent and dedup-safe. Foundation does
NOT implement the S3 store (a later ``dol``-plugin concern); it only guarantees
the interface is a plain ``MutableMapping``.

Storage layout follows app-data-lifecycle: data lives under
``~/.local/share/foley`` (overridable via ``$FOLEY_DATA_DIR``), never inside the
package.

Invariants wired here (see the skill):
    #1 ``LicenseRecord`` is the SSOT for the storage mode — ``store_sound`` reads
       ``record.license.cache_bytes_ok`` to choose by-value vs by-reference.
    #2 ``cache_bytes_ok`` (TOS/operational) is DISTINCT from
       ``redistribute_standalone_ok`` (copyright): a Freesound CC0 item is
       legally redistributable yet ``cache_bytes_ok=False``, so it is stored
       by-reference (URI + provenance only, NO bytes cached).
    #3 The meta store is safe by construction — ``sound_id`` values become
       on-disk filenames, and once SOURCE adapters mint external-derived ids
       (``freesound:123``, URLs, arbitrary strings) an unescaped id could carry
       ``/`` / ``..`` / drive letters / NUL and escape the meta dir or collide.
       :func:`make_meta_store` percent-encodes every id into a single, non-dot
       filename component (reversibly, so listing still yields the original id),
       and :func:`store_sound` rejects an empty id before any write. Hex content
       ids are unaffected (percent-encoding is a no-op on them).
"""

import hashlib
import os
from collections.abc import MutableMapping
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union
from urllib.parse import quote, unquote

from dol import Files, JsonFiles, mk_dirs_if_missing, wrap_kvs

from .base import GENERATION_AFFORDANCES, SoundRecord, StorageMode, reject_renamed

#: Hash algorithm used for content addressing (matches ``SoundRecord.hash_algo``).
HASH_ALGO = "sha256"

#: Suffix given to on-disk metadata files (keys stay the bare ``sound_id``).
META_FILE_SUFFIX = ".json"

#: Default data root (app-data-lifecycle: data under ``~/.local/share``, never in
#: the package). Override with ``$FOLEY_DATA_DIR``.
FOLEY_DATA_DIR = Path(
    os.environ.get("FOLEY_DATA_DIR", Path.home() / ".local" / "share" / "foley")
)
DEFAULT_AUDIO_DIR = FOLEY_DATA_DIR / "audio"
DEFAULT_META_DIR = FOLEY_DATA_DIR / "meta"
#: Content-credential sidecars (#9b): ``Mapping[content_id -> credential dict]``.
DEFAULT_PROVENANCE_DIR = FOLEY_DATA_DIR / "provenance"
#: Reproducible run-manifests (#11): ``Mapping[run_id -> RunManifest dict]``.
DEFAULT_RUN_DIR = FOLEY_DATA_DIR / "runs"
#: Per-session audition state (#12): ``sessions/{id}/{candidates,picks,rejects}/``.
DEFAULT_SESSION_DIR = FOLEY_DATA_DIR / "sessions"
#: Every paid generation's bytes + the request that produced them (#59).
DEFAULT_GENERATIONS_DIR = FOLEY_DATA_DIR / "generations"

#: A filesystem location (path or path-like string) for a local store root.
Rootdir = Union[str, "os.PathLike[str]"]


def content_key(data: bytes, *, algo: str = HASH_ALGO) -> str:
    """Return the content-address key for ``data`` — its hex digest.

    Using the hash as the key gives free deduplication (identical bytes map to
    the same key) and immutability (a key always names the exact same bytes).

    Args:
        data: The raw bytes to address (e.g. a FLAC archive blob).
        algo: A ``hashlib`` algorithm name (defaults to :data:`HASH_ALGO`).

    Returns:
        The lowercase hex digest of ``data`` under ``algo``.
    """
    return hashlib.new(algo, data).hexdigest()


def make_byte_store(rootdir: Rootdir = DEFAULT_AUDIO_DIR) -> MutableMapping[str, bytes]:
    """Build the content-addressable blob store: ``Mapping[content_key -> bytes]``.

    The local default is ``dol.Files`` (bytes values on disk). For cloud storage,
    build the equivalent store from any ``dol`` Mapping (e.g. an S3 store) and pass
    it directly to :func:`store_sound` instead of calling this factory — the
    ``store_sound`` gate treats ``sounds`` as an opaque ``MutableMapping``.

    Args:
        rootdir: Directory that holds the blobs (created if missing).

    Returns:
        A ``MutableMapping[str, bytes]`` keyed by :func:`content_key`.
    """
    return mk_dirs_if_missing(Files(str(rootdir)))


def _validate_sound_id(sound_id: str) -> str:
    """Reject ids that cannot become a safe, round-trippable meta filename.

    The path-*safety* is provided by :func:`_meta_filename`'s percent-encoding;
    this guard only rejects the degenerate cases encoding cannot rescue — a
    non-``str`` or an empty id (which would map to the ambiguous hidden file
    ``.json``). Fail-closed: a bad id is a programming error, not data.
    """
    if not isinstance(sound_id, str) or not sound_id:
        raise ValueError(f"sound_id must be a non-empty str, got {sound_id!r}")
    return sound_id


def _meta_filename(sound_id: str) -> str:
    """Map a ``sound_id`` to its on-disk metadata filename, escape-proof.

    Percent-encodes every character outside the URL-unreserved set (so ``/``,
    ``\\``, ``:``, ``..`` separators, NUL, etc. can never form a path that
    escapes the store root or spawns a subdirectory), then guarantees the result
    is not a dotfile (``dol`` silently omits leading-dot files from iteration —
    so an id like ``..`` or ``.foo`` would persist yet vanish from ``list()``).
    The mapping is injective and reversed by :func:`_meta_key`, so listing still
    yields the original ids. A no-op on hex content ids (all-unreserved).
    """
    encoded = quote(_validate_sound_id(sound_id), safe="")
    if encoded.startswith("."):  # dol skips dotfiles on iteration
        encoded = "%2E" + encoded[1:]
    return f"{encoded}{META_FILE_SUFFIX}"


def _meta_key(filename: str) -> str:
    """Invert :func:`_meta_filename`: on-disk filename -> original ``sound_id``."""
    if filename.endswith(META_FILE_SUFFIX):
        filename = filename[: -len(META_FILE_SUFFIX)]
    return unquote(filename)


def make_meta_store(
    rootdir: Rootdir = DEFAULT_META_DIR,
) -> MutableMapping[str, SoundRecord]:
    """Build the metadata store: ``Mapping[sound_id -> SoundRecord]`` (JSON files).

    ``SoundRecord`` values are (de)serialized transparently via the
    ``SerializableMixin`` (``to_dict`` / ``from_dict``); each record is written as
    a percent-encoded ``{sound_id}.json`` file while the store's keys stay the
    bare ``sound_id`` (invariant #3 — the id is escaped at this boundary so an
    externally-derived id can never escape ``rootdir`` or collide via ``/``/``..``).

    Args:
        rootdir: Directory that holds the metadata JSON files (created if missing).

    Returns:
        A ``MutableMapping[str, SoundRecord]`` keyed by ``sound_id``.
    """
    json_store = mk_dirs_if_missing(JsonFiles(str(rootdir)))  # values are dict
    return wrap_kvs(
        json_store,
        obj_of_data=SoundRecord.from_dict,  # dict -> SoundRecord on read
        data_of_obj=lambda rec: rec.to_dict(),  # SoundRecord -> dict on write
        # dol applies id_of_key to reach the underlying store and key_of_id when
        # listing, so id_of_key escapes the id + adds the suffix and key_of_id
        # reverses it — exposing bare sound_id keys over safe {enc}.json files.
        id_of_key=_meta_filename,  # sound_id -> escaped filename
        key_of_id=_meta_key,  # filename -> sound_id
    )


def make_provenance_store(
    rootdir: Rootdir = DEFAULT_PROVENANCE_DIR,
) -> MutableMapping[str, dict]:
    """Build the content-credential store: ``Mapping[content_id -> dict]`` (JSON files).

    The by-value sidecar carrier for #9b's portable "content credential" (a
    C2PA-shaped assertion dict written next to each generated clip; a
    ``SoundRecord``'s ``license.c2pa_manifest_ref`` points here by content id). Like
    :func:`make_meta_store` it escapes the id to a safe ``{enc}.json`` filename
    (invariant #3) while exposing bare ``content_id`` keys; values are plain dicts
    ((de)serialized natively by ``dol.JsonFiles``). Local ``dol.JsonFiles`` by
    default; swap in any ``dol`` Mapping to move sidecars to the cloud.

    Args:
        rootdir: Directory that holds the credential JSON files (created if missing).

    Returns:
        A ``MutableMapping[str, dict]`` keyed by content id.
    """
    json_store = mk_dirs_if_missing(JsonFiles(str(rootdir)))
    return wrap_kvs(json_store, id_of_key=_meta_filename, key_of_id=_meta_key)


def make_run_store(rootdir: Rootdir = DEFAULT_RUN_DIR) -> MutableMapping[str, dict]:
    """Build the run-artifact store: ``Mapping[run_id -> RunManifest dict]`` (JSON files).

    The by-value carrier for #11's reproducible run-manifests (one per instrumented
    ``find()`` / ``generate()`` / … ). An exact sibling of :func:`make_provenance_store`:
    escapes the ``run_id`` to a safe ``{enc}.json`` filename (invariant #3) while
    exposing bare ``run_id`` keys; values are plain dicts ((de)serialized by
    ``dol.JsonFiles``). Local by default; swap in any ``dol`` Mapping for the cloud.

    Args:
        rootdir: Directory that holds the run JSON files (created if missing).

    Returns:
        A ``MutableMapping[str, dict]`` keyed by ``run_id``.
    """
    json_store = mk_dirs_if_missing(JsonFiles(str(rootdir)))
    return wrap_kvs(json_store, id_of_key=_meta_filename, key_of_id=_meta_key)


def make_session_store(
    session_id: str = "default",
    name: str = "picks",
    *,
    rootdir: "Optional[Rootdir]" = None,
) -> MutableMapping[str, dict]:
    """Build a per-session JSON store: ``Mapping[key -> dict]`` under ``sessions/{id}/{name}/``.

    The by-value carrier for #12's audition state — one store per namespace
    (``candidates`` / ``picks`` / ``rejects``). A sibling of :func:`make_run_store`:
    percent-encodes each key to a safe ``{enc}.json`` filename (invariant #3) while
    exposing bare keys; values are plain dicts. Local by default; swap in any ``dol``
    Mapping for the cloud.

    Args:
        session_id: The session namespace (default ``'default'``).
        name: The store namespace within the session (``candidates`` / ``picks`` /
            ``rejects``).
        rootdir: Root sessions directory (default: :data:`DEFAULT_SESSION_DIR`).

    Returns:
        A ``MutableMapping[str, dict]`` keyed by the bare key.
    """
    root = (Path(rootdir) if rootdir else DEFAULT_SESSION_DIR) / session_id / name
    json_store = mk_dirs_if_missing(JsonFiles(str(root)))
    return wrap_kvs(json_store, id_of_key=_meta_filename, key_of_id=_meta_key)


@dataclass
class GenerationsCache:
    """Where paid generations are kept, so a paid response is never lost or paid twice (#59).

    Two ``dol`` mappings:

    * :attr:`audio` — ``content_key -> bytes``: every paid response, written **before**
      QC or ingest, so a quarantined or undecodable generation is still retrievable.
    * :attr:`requests` — ``request digest -> dict``: the canonical request (backend,
      prompt, the native request it resolves to, the model version) mapped to the
      content key plus the licence and notes it was generated under. An identical
      request is served from here instead of calling the provider again.
    """

    audio: MutableMapping[str, bytes]
    requests: MutableMapping[str, dict]

    def get(self, key: str) -> bytes:
        """The bytes of a kept generation, by content key or by request key (#107).

        A content key (``GenerationError.cache_key`` / ``IngestResult.cache_key``) reads
        the bytes directly; a request key (the digest a result's notes name: ``paid
        generation kept in the generations cache: <key>``) is resolved through its
        entry, following a fallback pointer. The bytes are the provider's response as
        received — before any watermark or repair — so a quarantined generation comes
        back exactly as it was paid for; :func:`foley.repair.repair_bytes` applies the
        same fixes ``generate`` would, and :func:`foley.index.ingest.ingest_one`
        (with the entry's ``license``) takes the result into a library. An entry with
        ``container: "video"`` keeps a muxed video answer whose audio is still to be
        taken out (#176; :func:`foley.sources.video.audio_track`, or replay the request).

        Raises:
            KeyError: If neither store knows ``key``.
        """
        if key in self.audio:
            return self.audio[key]
        entry = self.entry(key)
        content = entry.get("content_key")
        if content is None or content not in self.audio:
            raise KeyError(f"generation {key!r} has no bytes in the cache")
        return self.audio[content]

    def entry(self, request_key: str) -> dict:
        """The request entry kept under ``request_key`` (a fallback pointer is followed).

        Raises:
            KeyError: If ``request_key`` (or the entry it points at) is unknown.
        """
        entry = self.requests[request_key]
        if not isinstance(entry, dict):
            raise KeyError(f"generation {request_key!r} has an unreadable entry")
        target = entry.get("answered_by")
        if target:
            entry = self.requests[target]
            if not isinstance(entry, dict):
                raise KeyError(
                    f"generation {request_key!r} points at an unreadable entry"
                )
        return entry

    def find(
        self,
        prompt: Optional[str] = None,
        *,
        backend: Optional[str] = None,
        **affordances,
    ) -> "list[tuple[str, dict]]":
        """The kept generations matching ``prompt`` / ``backend`` / affordances, newest first.

        The way back to a paid clip whose key was not kept, e.g.
        ``foley.generations.find("a crisp apple bite", backend="elevenlabs", duration_s=1)``.
        Each item is ``(request_key, entry)``: ``entry["content_key"]`` (or :meth:`get`
        with either key) gives the bytes, ``entry["status"]`` how its ingest ended
        (``'quarantined'`` for a clip QC refused, absent while none has run). A
        fallback's alias entry is skipped (the request it answers is listed); an
        unreadable entry is skipped too. Numbers compare as floats (``duration_s=1``
        matches ``1.0``); an entry kept before an affordance was renamed is matched
        under its old name (``Affordance.renamed_from``), and passing an old name
        raises ``TypeError``. Entries kept by a foley before 0.0.43 carry no timestamp
        and come last, in listing order.
        """
        reject_renamed(affordances)
        video = affordances.get("video")
        if video is not None:  # kept by its key (#74): a value is found by its key
            from .sources.video import is_video_key, recorded_video_key

            if not is_video_key(video):
                try:
                    video = recorded_video_key(video)
                except FileNotFoundError:  # a path that is gone matches nothing
                    return []
            affordances = {**affordances, "video": video}
        hits = []
        for key in list(self.requests):
            try:
                entry = self.requests[key]
            except Exception:  # noqa: BLE001 - a bad entry is skipped, not a crash
                continue
            if not isinstance(entry, dict) or "answered_by" in entry:
                continue
            if "content_key" not in entry:
                continue
            if backend is not None and entry.get("backend") != backend:
                continue
            if prompt is not None and entry.get("prompt") != prompt:
                continue
            kept = entry.get("affordances") or {}
            if any(
                not _same_value(_kept_value(kept, k), v) for k, v in affordances.items()
            ):
                continue
            hits.append((key, entry))
        hits.sort(key=lambda kv: float(kv[1].get("at") or 0), reverse=True)
        return hits

    def evict(self, request_key: str, *, keep_audio: bool = False) -> None:
        """Forget a cached request (so the next identical one generates anew).

        Args:
            request_key: The request digest (noted on the result that cached it).
            keep_audio: Keep the bytes (default: delete them too, unless another
                request still points at them).
        """
        entry = self.requests.pop(request_key, None)
        if not entry or keep_audio:
            return
        key = entry.get("content_key")
        still_used = any(e.get("content_key") == key for e in self.requests.values())
        if key and not still_used and key in self.audio:
            del self.audio[key]


def _kept_value(kept: dict, name: str):
    """``kept[name]``, or the value an older entry kept under the name's old spelling."""
    if name in kept:
        return kept[name]
    aff = GENERATION_AFFORDANCES.get(name)
    return kept.get(aff.renamed_from) if aff and aff.renamed_from else None


def _same_value(a, b) -> bool:
    """``a == b``, with numbers (not bools) compared as floats."""
    numeric = all(
        isinstance(x, (int, float)) and not isinstance(x, bool) for x in (a, b)
    )
    return float(a) == float(b) if numeric else a == b


def make_generations_store(
    rootdir: Rootdir = DEFAULT_GENERATIONS_DIR,
) -> GenerationsCache:
    """Build the paid-generations cache (local files by default; any ``dol`` pair works).

    Args:
        rootdir: Directory holding ``audio/`` (bytes) and ``requests/`` (JSON).

    Returns:
        A :class:`GenerationsCache`.
    """
    root = Path(rootdir)
    return GenerationsCache(
        audio=make_byte_store(root / "audio"),
        requests=make_provenance_store(root / "requests"),
    )


def store_sound(
    record: SoundRecord,
    data: Optional[bytes] = None,
    *,
    sounds: MutableMapping[str, bytes],
    meta: MutableMapping[str, SoundRecord],
    cache_bytes_ok: Optional[bool] = None,
) -> SoundRecord:
    """Persist a sound, choosing by-value vs by-reference from ``cache_bytes_ok``.

    The choice is driven by the sound's own license (invariant #1): unless
    ``cache_bytes_ok`` is passed explicitly, it is read from
    ``record.license.cache_bytes_ok``. A sound whose bytes may NOT be cached
    (e.g. Freesound CC0, whose TOS forbids caching even though the file is legally
    redistributable — invariant #2) is stored **by reference**: no bytes are
    written, only its fetchable ``uri`` plus provenance.

    Args:
        record: The ``SoundRecord`` to persist; its nested ``license`` is the SSOT
            for the storage mode. Mutated in place with the resolved
            ``storage_mode`` / ``uri`` / ``content_sha256`` and written into
            ``meta``.
        data: The canonical archive bytes (FLAC). Required for by-value storage;
            for by-reference it is optional — if given, its hash is recorded in
            ``content_sha256`` for provenance but the bytes are NOT stored.
        sounds: The content-addressed byte store (see :func:`make_byte_store`).
        meta: The metadata store (see :func:`make_meta_store`).
        cache_bytes_ok: Optional override. ``None`` (the default) means "use
            ``record.license.cache_bytes_ok``".

    Returns:
        The same (mutated) ``record``, after it has been written into ``meta``.

    Raises:
        ValueError: If ``record.id`` is empty/non-``str`` (checked first, so a bad
            id never leaves an orphan blob), or if the sound resolves to
            by-reference storage but ``record.uri`` is empty (a by-reference sound
            must name a fetchable source URL).

    Note:
        The blob is written BEFORE the record so a crash can never leave a
        metadata reference dangling against a missing blob.
    """
    _validate_sound_id(record.id)  # fail-closed before any store side effect
    allow = record.license.cache_bytes_ok if cache_bytes_ok is None else cache_bytes_ok
    if allow and data is not None:
        key = content_key(data)
        sounds[key] = data  # blob first
        record.content_sha256 = key
        record.uri = key
        record.storage_mode = StorageMode.by_value
    else:
        # Validate before any mutation so the raising path leaves record untouched.
        if not record.uri:
            raise ValueError(
                "by-reference sound requires record.uri (a fetchable source URL)"
            )
        if data is not None:
            record.content_sha256 = content_key(data)  # provenance only, no store
        record.storage_mode = StorageMode.by_reference
    meta[record.id] = record  # record last
    return record
