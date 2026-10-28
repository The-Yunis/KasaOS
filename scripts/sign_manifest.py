"""Sign a release manifest with the offline Ed25519 key.

    python scripts/sign_manifest.py release/1.0.1/kasaos-manifest.json --key %USERPROFILE%\\.kasaos-signing\\private.pem

Verifies the result against kasaos/updates/trust.py before finishing, so a
release signed with an untrusted key is caught here rather than in the field.
"""

import argparse
import getpass
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cryptography.hazmat.primitives.serialization import load_pem_private_key  # noqa: E402

from kasaos.updates.manifest import SIGNATURE_NAME, parse_manifest, sign_manifest, verify_signature  # noqa: E402
from kasaos.updates.trust import TRUSTED_PUBLIC_KEYS  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest", type=Path)
    ap.add_argument("--key", type=Path, required=True)
    args = ap.parse_args()
    data = args.manifest.read_bytes()
    parse_manifest(data)  # refuse to sign something malformed
    pem = args.key.read_bytes()
    password = None
    if b"ENCRYPTED" in pem:
        password = getpass.getpass("Anahtar parolası: ").encode()
    key = load_pem_private_key(pem, password=password)
    sig = sign_manifest(data, key)
    verify_signature(data, sig, TRUSTED_PUBLIC_KEYS)
    out = args.manifest.with_name(SIGNATURE_NAME)
    out.write_bytes(sig)
    print("Signature written:", out)


if __name__ == "__main__":
    main()
