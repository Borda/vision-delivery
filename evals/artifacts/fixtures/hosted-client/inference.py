#!/usr/bin/env python3
"""Deterministic hosted-client fixture for artifact smoke validation."""

from __future__ import annotations

import argparse
import json
import os
import socket

ARTIFACT_KIND = "hosted-client"


def main() -> int:
    """Emit self-test output or validate runtime configuration."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        try:
            socket.create_connection(("127.0.0.1", 9), timeout=0.01)
        except RuntimeError as exc:
            if "network disabled during Sentinel self-test" not in str(exc):
                raise
        else:
            raise RuntimeError("self-test network guard was not active")
        print(
            json.dumps(
                {
                    "artifact_kind": "hosted-client",
                    "count": 1,
                    "predictions": [{"class": "fixture", "confidence": 0.9}],
                },
                sort_keys=True,
            )
        )
        return 0
    if not os.environ.get("SENTINEL_FIXTURE_TOKEN"):
        parser.error("SENTINEL_FIXTURE_TOKEN is required for this fixture's live path")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
