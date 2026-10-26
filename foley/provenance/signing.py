"""Build a C2PA signer from a certificate chain + private key (the #38 gotchas, solved once).

:func:`foley.weave` takes a ready ``c2pa.Signer`` as ``sign_cert`` (dependency-injected,
so foley pins no version-fragile signer-construction API). Building that signer is the
fiddly part; :func:`make_c2pa_signer` does it with the path that works across the
``c2pa-python`` versions tried (``Signer.from_callback``, signing with ``cryptography``,
raw ``r||s`` for ECDSA), which sidesteps ``Signer.from_info`` rejecting an empty
timestamp-authority URL for a local key.

* the cert chain is the end-entity certificate **followed by** its issuer, a C2PA
  conformant profile (KeyUsage=digitalSignature, EKU=emailProtection, Subject/Authority
  Key Identifiers);
* :func:`make_self_signed_c2pa_certs` makes such a chain for trying it out: a
  self-signed chain is *not* trusted by C2PA validators, so use a real CA for anything
  you publish.

Module top level is stdlib-only; ``c2pa`` (``foley[c2pa]``) and ``cryptography`` load
inside the functions.

>>> from foley.provenance.signing import SIGNING_ALGORITHMS
>>> sorted(SIGNING_ALGORITHMS)
['ed25519', 'es256', 'es384', 'es512', 'ps256', 'ps384', 'ps512']
"""

from __future__ import annotations

import datetime
from typing import Callable, Optional, Union

#: ``alg -> (hash name, ECDSA coordinate bytes or None)``; the SSOT for which algorithms
#: :func:`make_c2pa_signer` offers (PS* = RSA-PSS, ED25519 hashes internally).
SIGNING_ALGORITHMS: "dict[str, tuple[Optional[str], Optional[int]]]" = {
    "es256": ("SHA256", 32),
    "es384": ("SHA384", 48),
    "es512": ("SHA512", 66),
    "ps256": ("SHA256", None),
    "ps384": ("SHA384", None),
    "ps512": ("SHA512", None),
    "ed25519": (None, None),
}

#: Default algorithm: ES256 (ECDSA P-256 / SHA-256), what C2PA tooling expects first.
DEFAULT_SIGNING_ALG = "es256"

#: Defaults for :func:`make_self_signed_c2pa_certs`.
SELF_SIGNED_COMMON_NAME = "foley-dev-signer"
SELF_SIGNED_VALID_DAYS = 3650

PemLike = Union[str, bytes]


def _pem_text(pem: PemLike) -> str:
    return pem.decode("ascii") if isinstance(pem, bytes) else pem


def _callback_for(key, alg: str) -> "Callable[[bytes], bytes]":
    """The ``bytes -> signature`` function for ``key`` under ``alg`` (strategy per family)."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

    hash_name, coordinate_bytes = SIGNING_ALGORITHMS[alg]
    digest = getattr(hashes, hash_name)() if hash_name else None
    if alg.startswith("es"):
        if not isinstance(key, ec.EllipticCurvePrivateKey):
            raise ValueError(f"alg={alg!r} needs an EC private key, got {type(key).__name__}")

        def sign_ecdsa(data: bytes) -> bytes:
            r, s = decode_dss_signature(key.sign(data, ec.ECDSA(digest)))
            return r.to_bytes(coordinate_bytes, "big") + s.to_bytes(coordinate_bytes, "big")

        return sign_ecdsa
    if alg.startswith("ps"):
        if not isinstance(key, rsa.RSAPrivateKey):
            raise ValueError(f"alg={alg!r} needs an RSA private key, got {type(key).__name__}")
        pss = padding.PSS(mgf=padding.MGF1(digest), salt_length=digest.digest_size)
        return lambda data: key.sign(data, pss, digest)
    return key.sign  # ed25519


def make_c2pa_signer(
    cert_chain_pem: PemLike,
    private_key_pem: PemLike,
    *,
    alg: str = DEFAULT_SIGNING_ALG,
    tsa_url: Optional[str] = None,
    password: Optional[bytes] = None,
):
    """A ``c2pa.Signer`` for ``foley.weave(..., sign_cert=...)`` from a cert chain and key.

    Args:
        cert_chain_pem: The end-entity certificate followed by its issuer(s), PEM.
        private_key_pem: The signing key, PEM (PKCS#8 ``BEGIN PRIVATE KEY`` or SEC1).
        alg: One of :data:`SIGNING_ALGORITHMS` (default ``'es256'``); it must match the key.
        tsa_url: An RFC 3161 timestamp-authority URL (``None``: no timestamp).
        password: The key's passphrase, if it is encrypted.

    Raises:
        ValueError: An unknown ``alg``, or a key that does not fit it.
        ImportError: ``c2pa-python`` / ``cryptography`` missing (``pip install 'foley[c2pa]'``).
    """
    alg = alg.lower()
    if alg not in SIGNING_ALGORITHMS:
        raise ValueError(f"alg={alg!r}: choose one of {sorted(SIGNING_ALGORITHMS)}")
    try:
        import c2pa
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
    except ImportError as exc:
        raise ImportError(
            "make_c2pa_signer needs c2pa-python and cryptography: pip install 'foley[c2pa]'"
        ) from exc

    key_bytes = (
        private_key_pem.encode("ascii") if isinstance(private_key_pem, str) else private_key_pem
    )
    key = load_pem_private_key(key_bytes, password=password)
    return c2pa.Signer.from_callback(
        _callback_for(key, alg),
        getattr(c2pa.C2paSigningAlg, alg.upper()),
        _pem_text(cert_chain_pem),
        tsa_url,
    )


def make_self_signed_c2pa_certs(
    *,
    common_name: str = SELF_SIGNED_COMMON_NAME,
    valid_days: int = SELF_SIGNED_VALID_DAYS,
) -> "tuple[str, str]":
    """A throwaway C2PA-conformant ``(cert_chain_pem, private_key_pem)`` (ES256) for dev and tests.

    A CA plus an end-entity certificate with the profile C2PA requires. The chain is
    **not** trusted by validators; use a real CA for anything you publish. The key is
    PKCS#8 PEM.

    Lazy dependency: ``cryptography``.
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    now = datetime.datetime.now(datetime.timezone.utc)
    not_before, not_after = now - datetime.timedelta(days=1), now + datetime.timedelta(
        days=valid_days
    )
    ca_key, ee_key = (ec.generate_private_key(ec.SECP256R1()) for _ in range(2))

    def name(cn: str) -> "x509.Name":
        return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])

    def build(subject, issuer, key, issuer_key, serial, *extensions):
        builder = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(serial)
            .not_valid_before(not_before)
            .not_valid_after(not_after)
            .add_extension(
                x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False
            )
        )
        for extension, critical in extensions:
            builder = builder.add_extension(extension, critical=critical)
        return builder.sign(issuer_key, hashes.SHA256())

    ca_name = name(f"{common_name}-ca")
    ca = build(
        ca_name,
        ca_name,
        ca_key,
        ca_key,
        1,
        (x509.BasicConstraints(ca=True, path_length=None), True),
        (x509.KeyUsage(False, False, False, False, False, True, True, False, False), True),
    )
    ee = build(
        name(common_name),
        ca_name,
        ee_key,
        ca_key,
        2,
        (x509.BasicConstraints(ca=False, path_length=None), True),
        (x509.KeyUsage(True, False, False, False, False, False, False, False, False), True),
        (x509.ExtendedKeyUsage([ExtendedKeyUsageOID.EMAIL_PROTECTION]), True),
        (x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), False),
    )
    pem = serialization.Encoding.PEM
    chain = ee.public_bytes(pem) + ca.public_bytes(pem)
    key_pem = ee_key.private_bytes(
        pem, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    return chain.decode("ascii"), key_pem.decode("ascii")
