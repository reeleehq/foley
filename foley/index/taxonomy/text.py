"""The UCS term index: every row's terms, with the vocabulary's inflections.

Matching runs over a **closed vocabulary**: the words of the table's subcategories,
category names and synonyms. Instead of stemming the query (which mangles words:
``golden`` -> ``gold``, ``news`` -> ``new``), the index lists the regular inflections
of every vocabulary word (:func:`inflections`: ``-s``/``-es``/``-ies``, ``-ing``,
``-ed``, with the final ``e`` dropped and a final consonant doubled where English
does), so a query word is only lowercased and looked up: ``"rattling"`` meets the
``rattle`` synonym, ``"screens"`` the ``screen`` one, and ``"chicken"`` never meets
``chick``. Vocabulary words that are inflections of each other (``door`` and
``doors``, the ``DOORS`` category) share one *lemma*, so either spelling meets both.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping

from ...analysis import tokenize

_VOWELS = frozenset("aeiou")
#: Final consonants never doubled before ``-ing``/``-ed`` (``fixing``, ``rowing``).
_NEVER_DOUBLED = frozenset("wxy")
#: Endings that take ``-es`` (``buses``, ``boxes``, ``dishes``).
_SIBILANT_ENDINGS = ("s", "x", "z", "ch", "sh")

#: Shorter vocabulary words are not inflected (``be`` + ``d`` is ``bed``).
MIN_INFLECTED_LENGTH = 3

#: Vocabulary words that look like a regular inflection of another but are not
#: (``news`` is not the plural of ``new``, ``thing`` not ``the`` + ``-ing``, a
#: ``winding`` road not the ``WIND``): never linked to that other word.
NOT_INFLECTIONS: frozenset = frozenset(
    "news thing weed lemming rugged singed wicked copses earing bearing casing "
    "winding seed tired".split()
)


def _vowel_groups(word: str) -> int:
    """How many runs of vowels ``word`` has (a rough syllable count)."""
    return sum(
        1
        for i, c in enumerate(word)
        if c in _VOWELS and (i == 0 or word[i - 1] not in _VOWELS)
    )


def _doubles_final_consonant(word: str) -> bool:
    """Whether ``-ing``/``-ed`` double ``word``'s last letter (``drip`` -> ``dripping``).

    One syllable ending consonant-vowel-consonant; ``open`` (two) and ``rain`` (two
    vowels) do not double.
    """
    return (
        len(word) >= MIN_INFLECTED_LENGTH
        and _vowel_groups(word) == 1
        and word[-1] not in _VOWELS | _NEVER_DOUBLED
        and word[-2] in _VOWELS
        and word[-3] not in _VOWELS
    )


def inflections(word: str) -> "frozenset[str]":
    """The regular inflections of ``word`` (``word`` itself excluded).

    >>> sorted(inflections("rattle"))
    ['rattled', 'rattles', 'rattling']
    >>> sorted(inflections("drip")), sorted(inflections("buzz"))
    (['dripped', 'dripping', 'drips'], ['buzzed', 'buzzes', 'buzzing'])
    >>> sorted(inflections("cry")), sorted(inflections("open"))
    (['cried', 'cries', 'crying'], ['opened', 'opening', 'opens'])
    >>> inflections("up")
    frozenset()
    """
    if len(word) < MIN_INFLECTED_LENGTH or not word.isalpha():
        return frozenset()
    if word.endswith("y") and word[-2] not in _VOWELS:
        return frozenset({word[:-1] + "ies", word[:-1] + "ied", word + "ing"})
    if word.endswith("ie"):
        return frozenset({word + "s", word + "d", word[:-2] + "ying"})
    if word.endswith("e"):
        ing = word + "ing" if word.endswith(("ee", "oe", "ye")) else word[:-1] + "ing"
        return frozenset({word + "s", word + "d", ing})
    plural = word + "es" if word.endswith(_SIBILANT_ENDINGS) else word + "s"
    stem = word + word[-1] if _doubles_final_consonant(word) else word
    forms = {plural, stem + "ing", stem + "ed"}
    if word.endswith("o"):
        forms.add(word + "es")  # echoes, and echos
    return frozenset(forms)


@dataclass(frozen=True)
class Term:
    """One matchable term of a UCS row: its words, their lemmas, and where it came from.

    ``kind`` is ``"subcategory"``, ``"synonym"`` or ``"category"``.
    """

    catid: str
    words: "tuple[str, ...]"
    lemmas: "tuple[str, ...]"
    kind: str

    @property
    def text(self) -> str:
        """The term as written (lowercased, single-spaced)."""
        return " ".join(self.words)


@dataclass(frozen=True)
class TermIndex:
    """A table's terms keyed by lemma, the surface-form lexicon, and term sharing.

    Attributes:
        by_lemma: lemma -> every term with that lemma among its words.
        lexicon: surface word (a vocabulary word or an inflection of one) -> its lemmas.
        row_count: a term's lemmas -> in how many rows it appears, whatever its kind.
    """

    by_lemma: "Mapping[str, tuple[Term, ...]]"
    lexicon: "Mapping[str, frozenset[str]]"
    row_count: "Mapping[tuple[str, ...], int]"

    def lemmas(self, word: str) -> "frozenset[str]":
        """The lemmas a query word can be (empty if no vocabulary word has that form)."""
        return self.lexicon.get(word, frozenset())


def _row_texts(row) -> "list[tuple[str, str]]":
    """``(kind, text)`` of every term a ``UcsRow`` lists."""
    return [("subcategory", row.subcategory), ("category", row.category)] + [
        ("synonym", s) for s in row.synonyms
    ]


def _lemmatize(
    vocabulary: "set[str]",
    *,
    inflect: "Callable[[str], frozenset[str]]",
    not_inflections: frozenset,
) -> "tuple[dict[str, str], dict[str, frozenset[str]]]":
    """``(lemma_of, lexicon)`` over a closed vocabulary.

    A vocabulary word that is an inflection of a shorter one takes that one as its
    lemma (``doors`` -> ``door``); every other one is its own. The lexicon maps each
    vocabulary word to its lemma, and each inflection outside the vocabulary to the
    lemma of the word it inflects.
    """
    forms = {w: inflect(w) - not_inflections for w in vocabulary}
    lemma_of = {w: w for w in vocabulary}
    for word in sorted(vocabulary, key=lambda w: (len(w), w)):
        for form in forms[word] & vocabulary:
            if lemma_of[form] == form:
                lemma_of[form] = lemma_of[word]
    lexicon: dict[str, set] = defaultdict(set)
    for word in vocabulary:
        lexicon[word].add(lemma_of[word])
        for form in forms[word] - vocabulary:
            lexicon[form].add(lemma_of[word])
    return lemma_of, {w: frozenset(ls) for w, ls in lexicon.items()}


def category_rows(rows: Iterable) -> "dict[str, str]":
    """``category -> CatID`` of the row a category name alone lands on: its first
    generic (``GENERAL``/``MISC``) row, else its first row."""
    chosen: dict[str, tuple] = {}
    for i, row in enumerate(rows):
        key = (not row.is_generic, i)
        if row.category not in chosen or key < chosen[row.category][0]:
            chosen[row.category] = (key, row.catid)
    return {category: catid for category, (_, catid) in chosen.items()}


def build_term_index(
    rows: Iterable,
    *,
    inflect: "Callable[[str], frozenset[str]]" = inflections,
    not_inflections: frozenset = NOT_INFLECTIONS,
) -> TermIndex:
    """Index the subcategory, synonyms and category name of each ``UcsRow`` in ``rows``.

    A row lists a term once per kind, so a word that is both its category name and
    one of its synonyms counts as both. A category name is one term, on the
    category's representative row (:func:`category_rows`); a matcher lends it to
    the category's other rows. ``inflect`` gives a word's inflections (default
    :func:`inflections`); ``not_inflections`` are words never read as an inflection
    (default :data:`NOT_INFLECTIONS`).
    """
    rows = list(rows)
    representative = set(category_rows(rows).values())
    row_terms = [
        (row.catid, kind, tuple(tokenize(text)))
        for row in rows
        for kind, text in _row_texts(row)
    ]
    vocabulary = {w for _, _, words in row_terms for w in words}
    lemma_of, lexicon = _lemmatize(
        vocabulary, inflect=inflect, not_inflections=not_inflections
    )
    by_lemma: dict[str, list[Term]] = defaultdict(list)
    seen: set = set()
    for catid, kind, words in row_terms:
        lemmas = tuple(lemma_of[w] for w in words)
        if not words or (catid, kind, lemmas) in seen:
            continue
        seen.add((catid, kind, lemmas))
        if kind == "category" and catid not in representative:
            continue  # counted in row_count, indexed once per category
        term = Term(catid, words, lemmas, kind)
        for lemma in dict.fromkeys(lemmas):
            by_lemma[lemma].append(term)
    rows_listing = Counter(lemmas for _, lemmas in {(c, ls) for c, _, ls in seen})
    return TermIndex(
        by_lemma={w: tuple(ts) for w, ts in by_lemma.items()},
        lexicon=lexicon,
        row_count=dict(rows_listing),
    )
