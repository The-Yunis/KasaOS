"""Public Ed25519 keys trusted to sign release manifests (base64, raw 32 bytes).

Generate a key pair with scripts/generate_signing_key.py and paste the printed
public key here. The private key must never be committed. More than one key
may be listed to support key rotation.
"""

TRUSTED_PUBLIC_KEYS: list[str] = [
]
