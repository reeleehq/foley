"""The one text analyzer foley's keyword matchers share: lowercase ``[a-z0-9]+`` words.

The stdlib BM25 (:mod:`foley.index.indexes`) and the UCS keyword resolver
(:mod:`foley.index.taxonomy.text`) both tokenise with :func:`tokenize`, so a word the
keyword index sees is the word the taxonomy sees. Stdlib only, so any module can
import it without a cycle.
"""

from __future__ import annotations

import re

#: A word: a run of lowercase ASCII letters and digits (everything else separates).
WORD_PATTERN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> "list[str]":
    """The lowercase word/number tokens of ``text``.

    >>> tokenize("  Door-Creak, (Heavy)! 5.1")
    ['door', 'creak', 'heavy', '5', '1']
    """
    return WORD_PATTERN.findall(text.lower())
