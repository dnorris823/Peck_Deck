#!/usr/bin/env python
"""Generate a VAPID keypair for web push (FLEDGE Phase 7).

    python scripts/generate_vapid_keys.py

Prints the two lines to paste into `.env`. The keypair identifies *this server*
to browser push services (RFC 8292), so:

* Generate it once per deployment and keep it stable. Browsers bake the public
  key into their subscription — rotating the key silently invalidates every
  existing subscription, and each affected browser only recovers when the app
  next re-subscribes it.
* The private key is a signing key. Treat it like `JWT_SECRET`: env var only,
  never committed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402

from backend.notifications.push_sender import b64url_encode, public_key_bytes  # noqa: E402


def main() -> None:
    private = ec.generate_private_key(ec.SECP256R1())
    private_scalar = private.private_numbers().private_value.to_bytes(32, "big")

    print("# Web push (VAPID) — add to .env")
    print(f"VAPID_PRIVATE_KEY={b64url_encode(private_scalar)}")
    print(f"VAPID_PUBLIC_KEY={b64url_encode(public_key_bytes(private.public_key()))}")
    print("VAPID_SUBJECT=mailto:you@example.com")
    print()
    print("# The public key is also served to the frontend at GET /push/config,")
    print("# which derives it from the private key — VAPID_PUBLIC_KEY is only")
    print("# cross-checked, so the two can never silently disagree.")


if __name__ == "__main__":
    main()
