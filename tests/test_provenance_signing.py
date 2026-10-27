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

from foley.provenance import disclosure, make_c2pa_signer, make_self_signed_c2pa_certs  # noqa: E402
from foley.provenance.signing import (  # noqa: E402
    SIGNING_ALGORITHMS,
    _callback_for,
    c2pa_key_usage,
)  # noqa: E402

SR = 48_000

#: Validation-code prefixes about the signature / signing credential.
_SIGNER_CODES = ("claimSignature", "signingCredential")


def _key_pem(key, fmt=serialization.PrivateFormat.PKCS8) -> str:
    return key.private_bytes(
        serialization.Encoding.PEM, fmt, serialization.NoEncryption()
    ).decode("ascii")


def _ca_of(chain: str) -> str:
    """The issuer certificate (second PEM block) of a chain made by the helper."""
    marker = "-----BEGIN CERTIFICATE-----"
    return marker + chain.split(marker)[2]


def _rec(i=1):
    from foley.base import LicenseRecord, SoundRecord

    return SoundRecord(
        id=f"s{i}",
        caption=f"rain {i}",
        tags=["rain"],
        license=LicenseRecord(source="user", license_id="CC0-1.0", commercial_ok=True),
    )


def _sign_and_check(signer, trust_anchor: str, records=None):
    """Embed a mix manifest over ``records`` with ``signer``; read it back against ``trust_anchor``.

    Returns ALL validation failure codes (signature, credential AND manifest content). A
    signer with a garbage signature still embeds a manifest, so only these codes tell a
    real signature apart.
    """
    from foley import weave

    cred = disclosure.build_mix_credential(
        [_rec()] if records is None else records,
        asset_id="mix1",
        ai_disclosed=False,
        watermark_meta=None,
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
    return [f["code"] for f in report.get("validation_status") or []]


@pytest.mark.parametrize("n_ingredients", [0, 1, 3])
def test_a_signed_mix_validates_with_no_failure_codes(n_ingredients):
    """#134: every ``c2pa.placed`` references a declared ingredient, so nothing fails."""
    chain, key = make_self_signed_c2pa_certs()
    records = [_rec(i) for i in range(n_ingredients)]
    assert _sign_and_check(make_c2pa_signer(chain, key), _ca_of(chain), records) == []


def test_an_ingredient_whose_credential_fails_is_neither_declared_nor_placed():
    cred = disclosure.build_mix_credential(
        [_rec(1), object(), _rec(2)],
        asset_id="mix1",
        ai_disclosed=False,
        watermark_meta=None,
    )
    ingredients = cred["manifest"]["ingredients"]
    (actions,) = [
        a["data"]["actions"]
        for a in cred["manifest"]["assertions"]
        if a["label"] == "c2pa.actions"
    ]
    placed = [a["parameters"]["ingredientIds"] for a in actions[1:]]
    assert placed == [[i["instance_id"]] for i in ingredients]
    assert [i["foley_credential"]["asset_ref"] for i in ingredients] == ["s1", "s2"]
    chain, key = make_self_signed_c2pa_certs()
    signer = make_c2pa_signer(chain, key)
    assert _sign_and_check(signer, _ca_of(chain), [_rec(1), object(), _rec(2)]) == []


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
    codes = _sign_and_check(garbage, _ca_of(chain))
    assert any(c.startswith(_SIGNER_CODES) for c in codes)


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


def _ee_extensions(
    *, ca=False, digital_signature=True, eku=True, eku_oids=None
) -> list:
    """End-entity ``(extension, critical)`` pairs; each knob breaks one C2PA profile rule."""
    from cryptography import x509
    from cryptography.x509.oid import ExtendedKeyUsageOID

    exts = [
        (x509.BasicConstraints(ca=ca, path_length=None), True),
        (c2pa_key_usage(digital_signature=digital_signature, key_cert_sign=ca), True),
    ]
    if eku:
        oids = eku_oids or [ExtendedKeyUsageOID.EMAIL_PROTECTION]
        exts.append((x509.ExtendedKeyUsage(oids), True))
    return exts


def _chain_for(key, *, with_issuer=True, backdate_days=1, valid_days=30, **profile):
    """``(chain_pem, ca_pem)`` for ``key`` via the shipped dev-chain helper."""
    chain, _ = make_self_signed_c2pa_certs(
        key=key,
        end_entity_extensions=_ee_extensions(**profile),
        backdate_days=backdate_days,
        valid_days=valid_days,
    )
    ca = _ca_of(chain)
    return (chain if with_issuer else chain[: chain.index(ca)]), ca


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
        ({"backdate_days": 10, "valid_days": -5}, "expired"),
        ({"backdate_days": -5}, "not yet valid"),
    ],
)
def test_an_end_entity_cert_outside_the_c2pa_profile_is_refused_at_build_time(
    knob, match
):
    key = ec.generate_private_key(ec.SECP256R1())
    chain, _ = _chain_for(key, **knob)
    with pytest.raises(ValueError, match=match):
        make_c2pa_signer(chain, _key_pem(key))


@pytest.mark.parametrize(
    "oid_name", ["SERVER_AUTH", "CODE_SIGNING", "ANY_EXTENDED_KEY_USAGE"]
)
def test_an_unacceptable_eku_purpose_is_refused_at_build_time(oid_name):
    from cryptography.x509.oid import ExtendedKeyUsageOID

    key = ec.generate_private_key(ec.SECP256R1())
    chain, _ = _chain_for(key, eku_oids=[getattr(ExtendedKeyUsageOID, oid_name)])
    with pytest.raises(ValueError, match="ExtendedKeyUsage"):
        make_c2pa_signer(chain, _key_pem(key))


@pytest.mark.parametrize("chain", [None, 123, b"\xff\xfe"])
def test_a_non_pem_chain_value_is_a_value_error(chain):
    _, key = make_self_signed_c2pa_certs()
    with pytest.raises(ValueError, match="cert_chain_pem"):
        make_c2pa_signer(chain, key)


def test_a_small_rsa_key_is_refused_at_build_time():
    key = rsa.generate_private_key(65537, 1024)
    chain, _ = _chain_for(key)
    with pytest.raises(ValueError, match="1024 bits"):
        make_c2pa_signer(chain, _key_pem(key), alg="ps256")


def test_a_bare_leaf_is_accepted():
    key = ec.generate_private_key(ec.SECP256R1())
    chain, ca = _chain_for(key, with_issuer=False)
    assert chain.count("BEGIN CERTIFICATE") == 1
    assert _sign_and_check(make_c2pa_signer(chain, _key_pem(key)), ca) == []


@pytest.mark.parametrize("alg", [None, 256])
def test_a_non_string_alg_is_a_value_error(alg):
    chain, key = make_self_signed_c2pa_certs()
    with pytest.raises(ValueError, match="alg must be a string"):
        make_c2pa_signer(chain, key, alg=alg)


def test_a_failed_signing_is_logged_not_silent(caplog):
    """A signer built outside make_c2pa_signer (so unchecked) with a cert c2pa rejects."""
    from cryptography.x509.oid import ExtendedKeyUsageOID

    from foley import weave

    key = ec.generate_private_key(ec.SECP256R1())
    chain, _ = _chain_for(key, eku_oids=[ExtendedKeyUsageOID.SERVER_AUTH])
    signer = c2pa.Signer.from_callback(
        _callback_for(key, "es256"), c2pa.C2paSigningAlg.ES256, chain, None
    )
    cred = disclosure.build_mix_credential(
        [_rec()], asset_id="mix1", ai_disclosed=False, watermark_meta=None
    )
    with caplog.at_level("WARNING", logger="foley.weave"):
        assert not weave._sign_and_embed(
            np.zeros(100, "float32"), SR, cred, cert=signer
        )
    assert "C2PA signing failed" in caplog.text
    assert cred["signed"] is False
    assert cred["sign_error"].split(":")[0].isidentifier()


def test_self_signed_certs_accept_a_pem_key():
    key = ed25519.Ed25519PrivateKey.generate()
    chain, key_pem = make_self_signed_c2pa_certs(key=_key_pem(key))
    assert (
        _sign_and_check(make_c2pa_signer(chain, key_pem, alg="ed25519"), _ca_of(chain))
        == []
    )


def test_the_signed_mix_embeds_only_the_c2pa_ingredient_fields():
    """The full per-sound credential stays in the sidecar; c2pa embeds title/instance_id only."""
    from foley import weave

    chain, key = make_self_signed_c2pa_certs()
    cred = disclosure.build_mix_credential(
        [_rec(1), _rec(2)], asset_id="mix1", ai_disclosed=False, watermark_meta=None
    )
    store: dict = {}
    audio = np.zeros(SR // 2, "float32")
    assert weave._sign_and_embed(
        audio,
        SR,
        cred,
        cert=make_c2pa_signer(chain, key),
        provenance_store=store,
        asset_id="mix1",
    )
    report = json.loads(
        c2pa.Reader("audio/wav", io.BytesIO(store["mix1.c2pa.wav"])).json()
    )
    ingredients = report["manifests"][report["active_manifest"]]["ingredients"]
    assert len(ingredients) == 2
    for ingredient in ingredients:
        assert ingredient["title"] and ingredient["instance_id"]
        assert disclosure.INGREDIENT_CREDENTIAL_KEY not in ingredient
    assert all(
        i[disclosure.INGREDIENT_CREDENTIAL_KEY]["asset_ref"]
        for i in cred["manifest"]["ingredients"]
    )
