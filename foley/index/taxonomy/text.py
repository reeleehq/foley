"""Text normalisation for UCS keyword matching: lowercase, tokenise, light stemming.

Both sides of a keyword match (a sound's tags/caption, and a UCS row's subcategory,
synonyms and category name) go through :func:`terms`, so an inflected word meets
its base form: ``"doors"`` the ``DOORS`` category, ``"creaks"`` the ``creak``
synonym, ``"wooden"`` the ``WOOD`` subcategory. The stemmer is a few suffix rules,
not a linguistic one; since the same rules run on both sides, a word it mangles
still matches itself.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Iterable, Mapping

_NON_ALNUM = re.compile(r"[^a-z0-9]+")

#: ``(suffix, replacement, min_word_length)``, tried in order; the first that fits wins.
_SUFFIX_RULES: "tuple[tuple[str, str, int], ...]" = (
    ("ies", "y", 5),
    ("sses", "ss", 5),
    ("ches", "ch", 5),
    ("shes", "sh", 5),
    ("xes", "x", 4),
    ("ing", "", 6),
    ("ed", "", 5),
    ("en", "", 6),
    ("s", "", 4),
)
#: After ``-ing``/``-ed``, a doubled final consonant is undoubled (``dripp`` → ``drip``),
#: except these, which English doubles in the base form too (``fall``, ``buzz``).
_KEEP_DOUBLED = frozenset("lsz")


def normalize(text: str) -> str:
    """Lowercase and collapse non-alphanumerics to single spaces.

    >>> normalize("  Door-Creak, (Heavy)! ")
    'door creak heavy'
    """
    return _NON_ALNUM.sub(" ", text.lower()).strip()


def stem(word: str) -> str:
    """``word`` with one common English suffix stripped (``ss`` endings kept).

    >>> [stem(w) for w in ("doors", "creaks", "wooden", "dripping", "falling", "glass")]
    ['door', 'creak', 'wood', 'drip', 'fall', 'glass']
    """
    if word.endswith("ss"):
        return word
    for suffix, replacement, min_len in _SUFFIX_RULES:
        if len(word) >= min_len and word.endswith(suffix):
            base = word[: len(word) - len(suffix)] + replacement
            if (
                suffix in ("ing", "ed")
                and len(base) > 2
                and base[-1] == base[-2]
                and base[-1] not in _KEEP_DOUBLED
            ):
                base = base[:-1]
            return base
    return word


def terms(text: str) -> "tuple[str, ...]":
    """The normalised, stemmed words of ``text``.

    >>> terms("Heavy wooden doors creak")
    ('heavy', 'wood', 'door', 'creak')
    """
    return tuple(stem(w) for w in normalize(text).split())


@dataclass(frozen=True)
class Term:
    """One matchable term of a UCS row: its stemmed words and where it came from.

    ``kind`` is ``"subcategory"``, ``"synonym"`` or ``"category"``.
    """

    catid: str
    words: "tuple[str, ...]"
    kind: str


@dataclass(frozen=True)
class TermIndex:
    """Every row's terms, keyed by first word, with how many rows share each term.

    Built once per table (:attr:`~foley.index.taxonomy.model.UcsTable.term_index`),
    so a lookup touches only the terms that start with a word of the query.
    """

    by_first_word: "Mapping[str, tuple[Term, ...]]"
    row_count: "Mapping[tuple[str, ...], int]"


def build_term_index(rows: Iterable) -> TermIndex:
    """Index the subcategory, synonyms and category name of each ``UcsRow`` in ``rows``.

    A row lists a term once per kind, so a word that is both its category name and
    one of its synonyms counts as both. ``row_count`` says in how many rows a term
    appears, whatever its kind, so a term many rows share can count for less.
    """
    by_first: dict[str, list[Term]] = defaultdict(list)
    row_count: Counter = Counter()
    for row in rows:
        texts = [("subcategory", row.subcategory), ("category", row.category)] + [
            ("synonym", s) for s in row.synonyms
        ]
        indexed: set = set()
        for kind, text in texts:
            words = terms(text)
            if words and (kind, words) not in indexed:
                indexed.add((kind, words))
                by_first[words[0]].append(Term(row.catid, words, kind))
        row_count.update({words for _, words in indexed})
    return TermIndex(
        by_first_word={w: tuple(ts) for w, ts in by_first.items()},
        row_count=dict(row_count),
    )
