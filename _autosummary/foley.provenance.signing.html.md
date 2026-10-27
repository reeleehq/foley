# foley.provenance.signing

Build a C2PA signer from a certificate chain + private key (the #38 gotchas, solved once).

[`foley.weave()`](foley.weave.html.md#module-foley.weave) takes a ready `c2pa.Signer` as `sign_cert` (dependency-injected,
so foley pins no version-fragile signer-construction API). Building that signer is the
fiddly part; [`make_c2pa_signer()`](#foley.provenance.signing.make_c2pa_signer) does it with the path that works across the
`c2pa-python` versions tried (`Signer.from_callback`, signing with `cryptography`,
raw `r||s` for ECDSA), which sidesteps `Signer.from_info` rejecting an empty
timestamp-authority URL for a local key.

* the cert chain is the end-entity certificate **followed by** its issuer, a C2PA
  conformant profile (KeyUsage=digitalSignature, EKU=emailProtection, Subject/Authority
  Key Identifiers);
* [`make_self_signed_c2pa_certs()`](#foley.provenance.signing.make_self_signed_c2pa_certs) makes such a chain for trying it out: a
  self-signed chain is *not* trusted by C2PA validators, so use a real CA for anything
  you publish.

Module top level is stdlib-only; `c2pa` (`foley[c2pa]`) and `cryptography` load
inside the functions.

```pycon
>>> from foley.provenance.signing import SIGNING_ALGORITHMS
>>> sorted(SIGNING_ALGORITHMS)
['ed25519', 'es256', 'es384', 'es512', 'ps256', 'ps384', 'ps512']
```

### Module Attributes

| [`SIGNING_ALGORITHMS`](#foley.provenance.signing.SIGNING_ALGORITHMS)        | The SSOT for which algorithms [`make_c2pa_signer()`](#foley.provenance.signing.make_c2pa_signer) offers (PS\* = RSA-PSS).                                                       |
|----------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`DEFAULT_SIGNING_ALG`](#foley.provenance.signing.DEFAULT_SIGNING_ALG)       | ES256 (ECDSA P-256 / SHA-256), what C2PA tooling expects first.                                                                                                                  |
| [`SELF_SIGNED_COMMON_NAME`](#foley.provenance.signing.SELF_SIGNED_COMMON_NAME)   | Defaults for [`make_self_signed_c2pa_certs()`](#foley.provenance.signing.make_self_signed_c2pa_certs).                                                                                     |
| [`SELF_SIGNED_ORGANIZATION`](#foley.provenance.signing.SELF_SIGNED_ORGANIZATION)  | C2PA validators require an Organization in the end-entity subject.                                                                                                               |
| [`SELF_SIGNED_BACKDATE_DAYS`](#foley.provenance.signing.SELF_SIGNED_BACKDATE_DAYS) | Back-dating so a freshly made chain is valid despite clock skew.                                                                                                                 |
| [`MIN_RSA_KEY_BITS`](#foley.provenance.signing.MIN_RSA_KEY_BITS)          | A C2PA signing key must be at least this many bits when RSA (PS\* algorithms).                                                                                                   |
| [`C2PA_SIGNING_EKU_OIDS`](#foley.provenance.signing.C2PA_SIGNING_EKU_OIDS)     | ExtendedKeyUsage purposes c2pa-python accepts on a signing certificate (anyExtendedKeyUsage is refused: it is not on the list, and c2pa rejects it even beside a valid purpose). |

### Functions

| [`c2pa_key_usage`](#foley.provenance.signing.c2pa_key_usage)(\*\*on)                            | An `x509.KeyUsage` with every flag off except those set in `on` (lazy `cryptography`).   |
|----------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------|
| [`make_c2pa_signer`](#foley.provenance.signing.make_c2pa_signer)(cert_chain_pem, ...[, alg, ...]) | A `c2pa.Signer` for `foley.weave(..., sign_cert=...)` from a cert chain and key.         |
| [`make_self_signed_c2pa_certs`](#foley.provenance.signing.make_self_signed_c2pa_certs)(\*[, ...])            | A throwaway C2PA-conformant `(cert_chain_pem, private_key_pem)` for dev and tests.       |

### foley.provenance.signing.C2PA_SIGNING_EKU_OIDS *= frozenset({'1.3.6.1.4.1.62558.2.1', '1.3.6.1.5.5.7.3.36', '1.3.6.1.5.5.7.3.4', '1.3.6.1.5.5.7.3.8', '1.3.6.1.5.5.7.3.9'})*

ExtendedKeyUsage purposes c2pa-python accepts on a signing certificate (anyExtendedKeyUsage
is refused: it is not on the list, and c2pa rejects it even beside a valid purpose).

### foley.provenance.signing.DEFAULT_SIGNING_ALG *= 'es256'*

ES256 (ECDSA P-256 / SHA-256), what C2PA tooling expects first.

* **Type:**
  Default algorithm

### foley.provenance.signing.MIN_RSA_KEY_BITS *= 2048*

A C2PA signing key must be at least this many bits when RSA (PS\* algorithms).

### foley.provenance.signing.SELF_SIGNED_BACKDATE_DAYS *= 1*

Back-dating so a freshly made chain is valid despite clock skew.

### foley.provenance.signing.SELF_SIGNED_COMMON_NAME *= 'foley-dev-signer'*

Defaults for [`make_self_signed_c2pa_certs()`](#foley.provenance.signing.make_self_signed_c2pa_certs).

### foley.provenance.signing.SELF_SIGNED_ORGANIZATION *= 'foley'*

C2PA validators require an Organization in the end-entity subject.

### foley.provenance.signing.SIGNING_ALGORITHMS *: [dict](https://docs.python.org/3/builtins/stdtypes.html#dict)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), \_AlgSpec]* *= {'ed25519': \_AlgSpec(family='ed25519', hash_name=None, curve_name=None, ecdsa_bytes=None), 'es256': \_AlgSpec(family='ec', hash_name='SHA256', curve_name='SECP256R1', ecdsa_bytes=32), 'es384': \_AlgSpec(family='ec', hash_name='SHA384', curve_name='SECP384R1', ecdsa_bytes=48), 'es512': \_AlgSpec(family='ec', hash_name='SHA512', curve_name='SECP521R1', ecdsa_bytes=66), 'ps256': \_AlgSpec(family='rsa', hash_name='SHA256', curve_name=None, ecdsa_bytes=None), 'ps384': \_AlgSpec(family='rsa', hash_name='SHA384', curve_name=None, ecdsa_bytes=None), 'ps512': \_AlgSpec(family='rsa', hash_name='SHA512', curve_name=None, ecdsa_bytes=None)}*

The SSOT for which algorithms [`make_c2pa_signer()`](#foley.provenance.signing.make_c2pa_signer) offers (PS\* = RSA-PSS). A new
algorithm is a new row; `c2pa.C2paSigningAlg` must have the upper-cased name.

### foley.provenance.signing.c2pa_key_usage(\*\*on)

An `x509.KeyUsage` with every flag off except those set in `on` (lazy `cryptography`).

* **Return type:**
  x509.KeyUsage

### foley.provenance.signing.make_c2pa_signer(cert_chain_pem, private_key_pem, , alg='es256', tsa_url=None, password=None)

A `c2pa.Signer` for `foley.weave(..., sign_cert=...)` from a cert chain and key.

* **Parameters:**
  * **cert_chain_pem** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)]) – The end-entity certificate followed by its issuer(s), PEM. A bare
    leaf is accepted (not enforced): C2PA validators then need the issuer among their
    trust anchors, and it is not embedded in the manifest.
  * **private_key_pem** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes)]) – The signing key, PEM (PKCS#8 `BEGIN PRIVATE KEY` or SEC1).
  * **alg** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – One of [`SIGNING_ALGORITHMS`](#foley.provenance.signing.SIGNING_ALGORITHMS) (default `'es256'`); it must match the key.
  * **tsa_url** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]) – An RFC 3161 timestamp-authority URL (`None`: no timestamp).
  * **password** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes), [`None`](https://docs.python.org/3/builtins/constants.html#None)]) – The key’s passphrase, if it is encrypted (str or bytes).
* **Raises:**
  * [**ValueError**](https://docs.python.org/3/builtins/exceptions.html#ValueError) – An unknown or non-string `alg`, a key (or curve) that does not fit it,
        a chain that is not PEM or does not start with the key’s own certificate, or an
        end-entity certificate outside the C2PA signing profile (a CA, no digitalSignature,
        no acceptable ExtendedKeyUsage, an invalid validity window, or an RSA key under [`MIN_RSA_KEY_BITS`](#foley.provenance.signing.MIN_RSA_KEY_BITS)).
  * [**ImportError**](https://docs.python.org/3/builtins/exceptions.html#ImportError) – `c2pa-python` / `cryptography` missing (`pip install 'foley[c2pa]'`).

### foley.provenance.signing.make_self_signed_c2pa_certs(, common_name='foley-dev-signer', valid_days=3650, backdate_days=1, key=None, end_entity_extensions=None)

A throwaway C2PA-conformant `(cert_chain_pem, private_key_pem)` for dev and tests.

A CA plus an end-entity certificate with the profile C2PA requires. The chain is
**not** trusted by validators; use a real CA for anything you publish. The key is
PKCS#8 PEM.

* **Parameters:**
  * **key** ([`Union`](https://docs.python.org/3/library/typing.html#typing.Union)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`bytes`](https://docs.python.org/3/builtins/stdtypes.html#bytes), [`object`](https://docs.python.org/3/builtins/functions.html#object), [`None`](https://docs.python.org/3/builtins/constants.html#None)]) – the end-entity private key, any family `make_c2pa_signer` supports
    (a `cryptography` private key object, or PEM text/bytes). Default: a
    fresh ES256 (P-256) key. The CA is always ES256.
  * **end_entity_extensions** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`Iterable`](https://docs.python.org/3/library/typing.html#typing.Iterable)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`object`](https://docs.python.org/3/builtins/functions.html#object), [`bool`](https://docs.python.org/3/builtins/functions.html#bool)]]]) – `[(extension, critical), ...]` replacing the default
    end-entity profile (BasicConstraints, KeyUsage, ExtendedKeyUsage), e.g. to
    make a deliberately non-conformant chain for negative tests.
  * **backdate_days** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – days before now that the certificates start being valid
    (negative: not yet valid). A negative `valid_days` smaller in magnitude than
    `backdate_days` gives an expired chain.
* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]

Lazy dependency: `cryptography`.
