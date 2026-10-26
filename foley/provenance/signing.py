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
from dataclasses import dataclass
from typing import Callable, Optional, Union

@dataclass(frozen=True)
class _AlgSpec:
    """What an algorithm needs: the key family, its curve (EC), its hash (none for Ed25519)."""

    family: str  # 'ec' | 'rsa' | 'ed25519'
    hash_name: Optional[str] = None
    curve_name: Optional[str] = None
    ecdsa_bytes: Optional[int] = None  # r and s are each this many bytes


#: The SSOT for which algorithms :func:`make_c2pa_signer` offers (PS* = RSA-PSS). A new
#: algorithm is a new row; ``c2pa.C2paSigningAlg`` must have the upper-cased name.
SIGNING_ALGORITHMS: "dict[str, _AlgSpec]" = {
    "es256": _AlgSpec("ec", "SHA256", "SECP256R1", 32),
    "es384": _AlgSpec("ec", "SHA384", "SECP384R1", 48),
    "es512": _AlgSpec("ec", "SHA512", "SECP521R1", 66),
    "ps256": _AlgSpec("rsa", "SHA256"),
    "ps384": _AlgSpec("rsa", "SHA384"),
    "ps512": _AlgSpec("rsa", "SHA512"),
    "ed25519": _AlgSpec("ed25519"),
}

#: Default algorithm: ES256 (ECDSA P-256 / SHA-256), what C2PA tooling expects first.
DEFAULT_SIGNING_ALG = "es256"

#: Defaults for :func:`make_self_signed_c2pa_certs`.
SELF_SIGNED_COMMON_NAME = "foley-dev-signer"
SELF_SIGNED_VALID_DAYS = 3650
#: C2PA validators require an Organization in the end-entity subject.
SELF_SIGNED_ORGANIZATION = "foley"
#: Back-dating so a freshly made chain is valid despite clock skew.
SELF_SIGNED_BACKDATE_DAYS = 1

PemLike = Union[str, bytes]


def _pem_text(pem: PemLike) -> str:
    return pem.decode("ascii") if isinstance(pem, bytes) else pem


def _callback_for(key, alg: str) -> "Callable[[bytes], bytes]":
    """The ``bytes -> signature`` function for ``key`` under ``alg``.

    Raises:
        ValueError: ``key`` is not of the family (and, for EC, the curve) ``alg`` needs.
    """
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec, ed25519, padding, rsa
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

    spec = SIGNING_ALGORITHMS[alg]
    key_types = {
        "ec": ec.EllipticCurvePrivateKey,
        "rsa": rsa.RSAPrivateKey,
        "ed25519": ed25519.Ed25519PrivateKey,
    }
    if not isinstance(key, key_types[spec.family]):
        raise ValueError(
            f"alg={alg!r} needs a {spec.family.upper()} private key, got {type(key).__name__}"
        )
    if spec.family == "ed25519":
        return key.sign
    digest = getattr(hashes, spec.hash_name)()
    if spec.family == "rsa":
        pss = padding.PSS(mgf=padding.MGF1(digest), salt_length=digest.digest_size)
        return lambda data: key.sign(data, pss, digest)
    if key.curve.name != getattr(ec, spec.curve_name).name:
        raise ValueError(f"alg={alg!r} needs a {spec.curve_name} key, got {key.curve.name}")

    def sign_ecdsa(data: bytes) -> bytes:
        r, s = decode_dss_signature(key.sign(data, ec.ECDSA(digest)))
        return r.to_bytes(spec.ecdsa_bytes, "big") + s.to_bytes(spec.ecdsa_bytes, "big")

    return sign_ecdsa


def _check_chain_matches_key(cert_chain_pem: str, key) -> None:
    """Raise ``ValueError`` unless the chain is PEM, end-entity first, and holds ``key``'s cert."""
    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    try:
        certs = x509.load_pem_x509_certificates(cert_chain_pem.encode("ascii"))
    except ValueError as exc:
        raise ValueError(f"cert_chain_pem is not a PEM certificate chain: {exc}") from exc

    def public_der(public_key) -> bytes:
        return public_key.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)

    if public_der(certs[0].public_key()) != public_der(key.public_key()):
        raise ValueError(
            "the first certificate of cert_chain_pem does not belong to the private key: "
            "the chain is the end-entity certificate FOLLOWED BY its issuer"
        )


def make_c2pa_signer(
    cert_chain_pem: PemLike,
    private_key_pem: PemLike,
    *,
    alg: str = DEFAULT_SIGNING_ALG,
    tsa_url: Optional[str] = None,
    password: Optional[PemLike] = None,
):
    """A ``c2pa.Signer`` for ``foley.weave(..., sign_cert=...)`` from a cert chain and key.

    Args:
        cert_chain_pem: The end-entity certificate followed by its issuer(s), PEM.
        private_key_pem: The signing key, PEM (PKCS#8 ``BEGIN PRIVATE KEY`` or SEC1).
        alg: One of :data:`SIGNING_ALGORITHMS` (default ``'es256'``); it must match the key.
        tsa_url: An RFC 3161 timestamp-authority URL (``None``: no timestamp).
        password: The key's passphrase, if it is encrypted (str or bytes).

    Raises:
        ValueError: An unknown ``alg``, a key (or curve) that does not fit it, or a chain
            that is not PEM or does not start with the key's own certificate.
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
    key = load_pem_private_key(
        key_bytes,
        password=password.encode() if isinstance(password, str) else password,
    )
    chain = _pem_text(cert_chain_pem)
    callback = _callback_for(key, alg)
    _check_chain_matches_key(chain, key)
    return c2pa.Signer.from_callback(
        callback, getattr(c2pa.C2paSigningAlg, alg.upper()), chain, tsa_url
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
    not_before = now - datetime.timedelta(days=SELF_SIGNED_BACKDATE_DAYS)
    not_after = now + datetime.timedelta(days=valid_days)
    def _key_usage(**on) -> "x509.KeyUsage":
        flags = dict.fromkeys(
            (
                "digital_signature",
                "content_commitment",
                "key_encipherment",
                "data_encipherment",
                "key_agreement",
                "key_cert_sign",
                "crl_sign",
                "encipher_only",
                "decipher_only",
            ),
            False,
        )
        return x509.KeyUsage(**{**flags, **on})

    ca_key, ee_key = (ec.generate_private_key(ec.SECP256R1()) for _ in range(2))

    def name(cn: str) -> "x509.Name":
        return x509.Name(
            [
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, SELF_SIGNED_ORGANIZATION),
                x509.NameAttribute(NameOID.COMMON_NAME, cn),
            ]
        )

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
        (_key_usage(key_cert_sign=True, crl_sign=True), True),
    )
    ee = build(
        name(common_name),
        ca_name,
        ee_key,
        ca_key,
        2,
        (x509.BasicConstraints(ca=False, path_length=None), True),
        (_key_usage(digital_signature=True), True),
        (x509.ExtendedKeyUsage([ExtendedKeyUsageOID.EMAIL_PROTECTION]), True),
        (x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), False),
    )
    pem = serialization.Encoding.PEM
    chain = ee.public_bytes(pem) + ca.public_bytes(pem)
    key_pem = ee_key.private_bytes(
        pem, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    return chain.decode("ascii"), key_pem.decode("ascii")
