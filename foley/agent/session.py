"""Session-scoped audition state — cached candidates, picks, and rejects (#12).

An interactive/agentic foley loop is stateful: ``find`` / ``search`` surface candidates,
the user (or an LLM) **previews**, **picks** and **rejects** them, and ``plan`` / ``weave``
then consume the picks. :class:`SessionStore` holds that state in three namespaced ``dol``
stores under ``FOLEY_DATA_DIR/sessions/{id}/`` (swap in any Mapping for the cloud):

* **candidates** — the full ``Candidate.to_dict()`` keyed by sound id; the *rehydration
  source* so ``plan`` / ``weave`` can rebuild real :class:`~foley.base.Candidate` objects
  from ids without the agent ever handling the heavy object. Internal — never exposed as
  writable MCP CRUD (protects the ``from_dict`` source).
* **picks** — accepted sounds (+ optional layer/onset) that ``plan`` folds into a timeline.
* **rejects** — dismissed sounds that feed ``refine``'s relevance feedback.

Stdlib + ``dol`` only (via :mod:`foley.stores`); keeps ``import foley`` dol-only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..base import Candidate


def _candidate_id(candidate) -> "Optional[str]":
    """The sound id that keys a candidate in the session cache."""
    return getattr(getattr(candidate, "sound", None), "id", None)


@dataclass
class SessionStore:
    """Three namespaced stores for one audition session (candidates / picks / rejects).

    Each store defaults to a :func:`foley.stores.make_session_store` JSON store; tests
    inject plain dicts. All values are JSON-safe dicts.

    Args:
        session_id: The session namespace: one plain name
            (:func:`foley.stores.check_session_id`, else ``ValueError``).
        candidates / picks / rejects: Optional injected ``MutableMapping`` stores.
    """

    session_id: str = "default"
    candidates: Optional[dict] = None
    picks: Optional[dict] = None
    rejects: Optional[dict] = None

    def __post_init__(self):
        from ..stores import check_session_id, make_session_store

        check_session_id(self.session_id)  # injected stores too: one rule for an id
        if self.candidates is None:
            self.candidates = make_session_store(self.session_id, "candidates")
        if self.picks is None:
            self.picks = make_session_store(self.session_id, "picks")
        if self.rejects is None:
            self.rejects = make_session_store(self.session_id, "rejects")

    # -- candidate cache (the rehydration source) ---------------------------

    def cache_candidates(self, candidates: "list[Candidate]") -> int:
        """Cache each candidate's full ``to_dict()`` keyed by sound id; return the count cached."""
        n = 0
        for c in candidates:
            sid = _candidate_id(c)
            if sid:
                self.candidates[sid] = c.to_dict()
                n += 1
        return n

    def rehydrate(self, ids: "list[str]") -> "list[Candidate]":
        """Rebuild :class:`~foley.base.Candidate` objects for ``ids`` from the cache.

        Missing ids are skipped. Uses ``Candidate.from_dict`` (rebuilds the nested
        ``SoundRecord`` / ``LicenseRecord`` / ``Verdict``).
        """
        from ..base import Candidate

        out: "list[Candidate]" = []
        for sid in ids:
            d = self.candidates.get(sid)
            if d is not None:
                out.append(Candidate.from_dict(d))
        return out

    # -- picks / rejects ----------------------------------------------------

    def add_pick(
        self,
        sound_id: str,
        *,
        layer: "Optional[str]" = None,
        onset: "Optional[float]" = None,
    ) -> int:
        """Persist an accepted pick (+ optional layer/onset); return the pick count."""
        self.picks[sound_id] = {"sound_id": sound_id, "layer": layer, "onset": onset}
        return len(self.picks)

    def drop_pick(self, sound_id: str) -> int:
        """Remove a pick (idempotent); return the remaining pick count."""
        if sound_id in self.picks:
            del self.picks[sound_id]
        return len(self.picks)

    def list_picks(self) -> "list[dict]":
        """All persisted picks."""
        return [self.picks[k] for k in self.picks]

    def picked_ids(self) -> "list[str]":
        """The picked sound ids."""
        return list(self.picks)

    def add_reject(self, sound_id: str, *, reason: "Optional[str]" = None) -> int:
        """Record a rejected sound (feeds ``refine`` relevance feedback); return the count."""
        self.rejects[sound_id] = {"sound_id": sound_id, "reason": reason}
        return len(self.rejects)

    def list_rejects(self) -> "list[dict]":
        """All recorded rejects."""
        return [self.rejects[k] for k in self.rejects]

    def rejected_ids(self) -> "list[str]":
        """The rejected sound ids."""
        return list(self.rejects)
