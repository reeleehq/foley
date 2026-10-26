"""``make_c2pa_signer`` / ``make_self_signed_c2pa_certs`` (#44).

Needs ``c2pa-python`` and ``cryptography`` (``foley[c2pa]``); ``importorskip``-guarded so CI
stays hermetic without them. The load-bearing test is the issue's acceptance: ``weave``
with ``sign_cert=make_c2pa_signer(cert, key)`` embeds a manifest ``c2pa`` reads back.
"""

import io
import json

import pytest

c2pa = pytest.importorskip("c2pa")
pytest.importorskip("cryptography")
np = pytest.importorskip("numpy")

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa  # noqa: E402

from foley.provenance import make_c2pa_signer, make_self_signed_c2pa_certs  # noqa: E402
from foley.provenance.signing import SIGNING_ALGORITHMS  # noqa: E402

SR = 48_000

#: Validation codes about the signature / signing credential (not the manifest content).
_SIGNER_CODES = ("claimSignature", "signingCredential")


def _key_pem(key, fmt=serialization.PrivateFormat.PKCS8) -> str:
    return key.private_bytes(
        serialization.Encoding.PEM, fmt, serialization.NoEncryption()
    ).decode("ascii")


def _ca_of(chain: str) -> str:
    """The issuer certificate (second PEM block) of a chain made by the helper."""
    marker = "-----BEGIN CERTIFICATE-----"
    return marker + chain.split(marker)[2]


def _sign_and_check(signer, trust_anchor: str):
    """Embed a manifest with ``signer`` and read it back against ``trust_anchor``.

    Returns the validation failure codes. A signer with a garbage signature still embeds
    a manifest, so only these codes tell a real signature apart. (The mix's own action
    assertion can raise ``assertion.action.ingredientMismatch``: that is the manifest
    content, not the signer, so the checks look at the signature and credential codes.)
    """
    from foley import weave
    from foley.base import LicenseRecord, SoundRecord

    rec = SoundRecord(
        id="s1",
        caption="rain",
        tags=["rain"],
        license=LicenseRecord(source="user", license_id="CC0-1.0", commercial_ok=True),
    )
    cred = weave._build_mix_credential(
        [rec], asset_id="mix1", ai_disclosed=False, watermark_meta=None
    )
    store: dict = {}
    audio = (0.1 * np.random.default_rng(0).standard_normal(SR // 2)).astype("float32")
    assert weave._sign_and_embed(
        audio, SR, cred, cert=signer, provenance_store=store, asset_id="mix1"
    )
    context = (
        c2pa.ContextBuilder()
        .with_settings(c2pa.Settings.from_dict({"trust": {"trust_anchors": trust_anchor}}))
        .build()
    )
    report = json.loads(
        c2pa.Reader(
            "audio/wav", io.BytesIO(store["mix1.c2pa.wav"]), context=context
        ).json()
    )
    codes = [f["code"] for f in report.get("validation_status") or []]
    return [c for c in codes if c.startswith(_SIGNER_CODES)]


def test_self_signed_certs_make_a_signer_whose_signature_validates():
    chain, key = make_self_signed_c2pa_certs()
    assert chain.count("BEGIN CERTIFICATE") == 2  # end-entity + CA
    assert "BEGIN PRIVATE KEY" in key  # PKCS#8
    assert _sign_and_check(make_c2pa_signer(chain, key), _ca_of(chain)) == []


def test_the_check_would_catch_a_bad_signature():
    chain, _ = make_self_signed_c2pa_certs()
    garbage = c2pa.Signer.from_callback(
        lambda data: b"\x01" * 64, c2pa.C2paSigningAlg.ES256, chain, None
    )
    assert _sign_and_check(garbage, _ca_of(chain)) != []


def test_certs_and_key_may_be_bytes():
    chain, key = make_self_signed_c2pa_certs()
    signer = make_c2pa_signer(chain.encode(), key.encode())
    assert _sign_and_check(signer, _ca_of(chain)) == []


def test_a_sec1_key_is_accepted_too():
    chain, key = make_self_signed_c2pa_certs()
    loaded = serialization.load_pem_private_key(key.encode(), password=None)
    sec1 = _key_pem(loaded, serialization.PrivateFormat.TraditionalOpenSSL)
    assert "BEGIN EC PRIVATE KEY" in sec1
    assert _sign_and_check(make_c2pa_signer(chain, sec1), _ca_of(chain)) == []


def test_an_encrypted_key_takes_a_str_or_bytes_password():
    chain, key = make_self_signed_c2pa_certs()
    loaded = serialization.load_pem_private_key(key.encode(), password=None)
    encrypted = loaded.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(b"pw"),
    )
    for password in ("pw", b"pw"):
        signer = make_c2pa_signer(chain, encrypted, password=password)
        assert _sign_and_check(signer, _ca_of(chain)) == []


@pytest.mark.parametrize(
    "alg, key",
    [
        ("es256", ec.generate_private_key(ec.SECP256R1())),
        ("es384", ec.generate_private_key(ec.SECP384R1())),
        ("es512", ec.generate_private_key(ec.SECP521R1())),
        ("ps256", rsa.generate_private_key(65537, 2048)),
        ("ps512", rsa.generate_private_key(65537, 2048)),
        ("ed25519", ed25519.Ed25519PrivateKey.generate()),
    ],
)
def test_every_algorithm_produces_a_signature_its_public_key_verifies(alg, key):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

    from foley.provenance.signing import _callback_for

    spec = SIGNING_ALGORITHMS[alg]
    data = b"payload"
    signature = _callback_for(key, alg)(data)
    pub = key.public_key()
    digest = getattr(hashes, spec.hash_name)() if spec.hash_name else None
    if spec.family == "ec":
        n = spec.ecdsa_bytes
        assert len(signature) == 2 * n  # raw r||s
        der = encode_dss_signature(
            int.from_bytes(signature[:n], "big"), int.from_bytes(signature[n:], "big")
        )
        pub.verify(der, data, ec.ECDSA(digest))
    elif spec.family == "rsa":
        pss = padding.PSS(mgf=padding.MGF1(digest), salt_length=digest.digest_size)
        pub.verify(signature, data, pss, digest)
    else:
        pub.verify(signature, data)


def test_the_algorithm_table_matches_the_c2pa_enum():
    assert {a.upper() for a in SIGNING_ALGORITHMS} <= set(c2pa.C2paSigningAlg.__members__)


def test_a_key_that_does_not_fit_the_algorithm_is_a_clear_error():
    chain, key = make_self_signed_c2pa_certs()
    with pytest.raises(ValueError, match="RSA private key"):
        make_c2pa_signer(chain, key, alg="ps256")
    with pytest.raises(ValueError, match="ED25519 private key"):
        make_c2pa_signer(chain, key, alg="ed25519")
    with pytest.raises(ValueError, match="SECP384R1"):
        make_c2pa_signer(chain, key, alg="es384")  # a P-256 key
    with pytest.raises(ValueError, match="choose one of"):
        make_c2pa_signer(chain, key, alg="rot13")


def test_a_reversed_or_unparseable_chain_is_refused_when_the_signer_is_built():
    chain, key = make_self_signed_c2pa_certs()
    marker = "-----BEGIN CERTIFICATE-----"
    _, ee, ca = chain.split(marker)
    with pytest.raises(ValueError, match="FOLLOWED BY"):
        make_c2pa_signer(marker + ca + marker + ee, key)
    with pytest.raises(ValueError, match="not a PEM"):
        make_c2pa_signer("not a certificate", key)
