from __future__ import annotations

import verify_bundle


def test_bundle_verifier_passes() -> None:
    assert verify_bundle.main() == 0
