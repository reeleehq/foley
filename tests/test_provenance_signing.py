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
        .with_settings(
            c2pa.Settings.from_dict({"trust": {"trust_anchors": trust_anchor}})
        )
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
    assert {a.upper() for a in SIGNING_ALGORITHMS} <= set(
        c2pa.C2paSigningAlg.__members__
    )


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


# --- end-entity profile checks (#135) ---------------------------------------------------


def _chain_for(key, *, ca=False, digital_signature=True, eku=True, with_issuer=True):
    """A ``(chain_pem, ca_pem)`` whose end-entity cert holds ``key``'s public key.

    The knobs break one profile rule each; the issuer is an ES256 CA made here.
    """
    import datetime

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    def name(cn):
        return x509.Name(
            [
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, "foley-test"),
                x509.NameAttribute(NameOID.COMMON_NAME, cn),
            ]
        )

    def usage(**on):
        flags = dict.fromkeys(
            [
                "digital_signature",
                "content_commitment",
                "key_encipherment",
                "data_encipherment",
                "key_agreement",
                "key_cert_sign",
                "crl_sign",
                "encipher_only",
                "decipher_only",
            ],
            False,
        )
        return x509.KeyUsage(**{**flags, **on})

    now = datetime.datetime.now(datetime.timezone.utc)
    ca_key = ec.generate_private_key(ec.SECP256R1())

    def build(subject, issuer, pub, extensions):
        b = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(pub)
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=30))
            .add_extension(
                x509.SubjectKeyIdentifier.from_public_key(pub), critical=False
            )
        )
        for ext in extensions:
            b = b.add_extension(ext, critical=True)
        if issuer != subject:
            b = b.add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
                critical=False,
            )
        return b.sign(ca_key, hashes.SHA256())

    ca_cert = build(
        name("ca"),
        name("ca"),
        ca_key.public_key(),
        [x509.BasicConstraints(ca=True, path_length=None), usage(key_cert_sign=True)],
    )
    extensions = [
        x509.BasicConstraints(ca=ca, path_length=None),
        usage(digital_signature=digital_signature, key_cert_sign=ca),
    ]
    if eku:
        extensions.append(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.EMAIL_PROTECTION]))
    ee = build(
        name("ee"),
        name("ca"),
        key.public_key(),
        extensions,
    )
    pem = serialization.Encoding.PEM
    ca_pem = ca_cert.public_bytes(pem).decode("ascii")
    chain = ee.public_bytes(pem).decode("ascii") + (ca_pem if with_issuer else "")
    return chain, ca_pem


@pytest.mark.parametrize(
    "alg, key",
    [
        ("es384", ec.generate_private_key(ec.SECP384R1())),
        ("ps256", rsa.generate_private_key(65537, 2048)),
        ("ps384", rsa.generate_private_key(65537, 2048)),
        ("ps512", rsa.generate_private_key(65537, 2048)),
        ("ed25519", ed25519.Ed25519PrivateKey.generate()),
    ],
)
def test_other_algorithms_sign_a_manifest_that_reads_back_clean(alg, key):
    chain, ca = _chain_for(key)
    signer = make_c2pa_signer(chain, _key_pem(key), alg=alg)
    assert _sign_and_check(signer, ca) == []


@pytest.mark.parametrize(
    "knob, match",
    [
        ({"ca": True}, "CA certificate"),
        ({"digital_signature": False}, "digitalSignature"),
        ({"eku": False}, "ExtendedKeyUsage"),
    ],
)
def test_an_end_entity_cert_outside_the_c2pa_profile_is_refused_at_build_time(
    knob, match
):
    key = ec.generate_private_key(ec.SECP256R1())
    chain, _ = _chain_for(key, **knob)
    with pytest.raises(ValueError, match=match):
        make_c2pa_signer(chain, _key_pem(key))


def test_a_small_rsa_key_is_refused_at_build_time():
    key = rsa.generate_private_key(65537, 1024)
    chain, _ = _chain_for(key)
    with pytest.raises(ValueError, match="1024 bits"):
        make_c2pa_signer(chain, _key_pem(key), alg="ps256")


def test_a_bare_leaf_is_accepted():
    key = ec.generate_private_key(ec.SECP256R1())
    chain, _ = _chain_for(key, with_issuer=False)
    assert chain.count("BEGIN CERTIFICATE") == 1
    make_c2pa_signer(chain, _key_pem(key))


@pytest.mark.parametrize("alg", [None, 256])
def test_a_non_string_alg_is_a_value_error(alg):
    chain, key = make_self_signed_c2pa_certs()
    with pytest.raises(ValueError, match="alg must be a string"):
        make_c2pa_signer(chain, key, alg=alg)


def test_a_failed_signing_is_logged_not_silent(caplog):
    from foley import weave

    cred = {"manifest": {"not": "a valid manifest"}}
    with caplog.at_level("WARNING", logger="foley.weave"):
        assert (
            weave._sign_and_embed(np.zeros(100, "float32"), SR, cred, cert=object())
            is False
        )
    assert "C2PA signing failed" in caplog.text
