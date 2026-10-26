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


def _key_pem(key, fmt=serialization.PrivateFormat.PKCS8) -> str:
    return key.private_bytes(
        serialization.Encoding.PEM, fmt, serialization.NoEncryption()
    ).decode("ascii")


def _sign_and_read(signer) -> dict:
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
    return json.loads(c2pa.Reader("audio/wav", io.BytesIO(store["mix1.c2pa.wav"])).json())


def test_self_signed_certs_make_a_signer_that_embeds_a_readable_manifest():
    chain, key = make_self_signed_c2pa_certs()
    assert chain.count("BEGIN CERTIFICATE") == 2  # end-entity + CA
    assert "BEGIN PRIVATE KEY" in key  # PKCS#8
    assert _sign_and_read(make_c2pa_signer(chain, key)).get("active_manifest")


def test_certs_and_key_may_be_bytes():
    chain, key = make_self_signed_c2pa_certs()
    signer = make_c2pa_signer(chain.encode(), key.encode())
    assert _sign_and_read(signer).get("active_manifest")


def test_a_sec1_key_is_accepted_too():
    chain, key = make_self_signed_c2pa_certs()
    loaded = serialization.load_pem_private_key(key.encode(), password=None)
    sec1 = _key_pem(loaded, serialization.PrivateFormat.TraditionalOpenSSL)
    assert "BEGIN EC PRIVATE KEY" in sec1
    assert _sign_and_read(make_c2pa_signer(chain, sec1)).get("active_manifest")


@pytest.mark.parametrize(
    "alg, key",
    [
        ("es384", ec.generate_private_key(ec.SECP384R1())),
        ("ps256", rsa.generate_private_key(65537, 2048)),
        ("ed25519", ed25519.Ed25519PrivateKey.generate()),
    ],
)
def test_every_key_family_gets_a_callback_that_signs(alg, key):
    from foley.provenance.signing import _callback_for

    signature = _callback_for(key, alg)(b"payload")
    assert isinstance(signature, bytes) and signature
    if alg == "es384":
        assert len(signature) == 96  # raw r||s, 48 bytes each


def test_the_algorithm_table_matches_the_c2pa_enum():
    assert {a.upper() for a in SIGNING_ALGORITHMS} <= set(c2pa.C2paSigningAlg.__members__)


def test_a_key_that_does_not_fit_the_algorithm_is_a_clear_error():
    chain, key = make_self_signed_c2pa_certs()
    with pytest.raises(ValueError, match="RSA private key"):
        make_c2pa_signer(chain, key, alg="ps256")
    with pytest.raises(ValueError, match="choose one of"):
        make_c2pa_signer(chain, key, alg="rot13")
