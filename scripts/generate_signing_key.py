"""Create the offline Ed25519 release-signing key pair.

    python scripts/generate_signing_key.py [--out DIR]

Writes an encrypted private key OUTSIDE the repository (default
%USERPROFILE%\\.kasaos-signing) and prints the public key to paste into
kasaos/updates/trust.py. Keep the private key and its password offline and
backed up; losing it means existing installs cannot verify new releases.
"""

import argparse
import base64
import getpass
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (BestAvailableEncryption, Encoding, NoEncryption,
                                                          PrivateFormat, PublicFormat)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path.home() / ".kasaos-signing")
    ap.add_argument("--no-password", action="store_true", help="only for throwaway test keys")
    args = ap.parse_args()
    target = args.out / "private.pem"
    if target.exists():
        raise SystemExit(f"{target} already exists; refusing to overwrite a signing key.")
    repo = Path(__file__).resolve().parents[1]
    if repo in args.out.resolve().parents or args.out.resolve() == repo:
        raise SystemExit("Refusing to write the private key inside the repository.")
    if args.no_password:
        enc = NoEncryption()
    else:
        pw = getpass.getpass("Yeni anahtar parolası: ")
        if pw != getpass.getpass("Tekrar: ") or len(pw) < 12:
            raise SystemExit("Parolalar uyuşmuyor veya 12 karakterden kısa.")
        enc = BestAvailableEncryption(pw.encode())
    key = Ed25519PrivateKey.generate()
    args.out.mkdir(parents=True, exist_ok=True)
    target.write_bytes(key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, enc))
    pub = base64.b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
    (args.out / "public.txt").write_text(pub, encoding="ascii")
    print("Private key:", target)
    print("Public key (add to kasaos/updates/trust.py TRUSTED_PUBLIC_KEYS):")
    print(pub)


if __name__ == "__main__":
    main()
