# Fixture Run Contract

- Artifact kind: `hosted-client`
- Provider dependency: simulated provider
- Python requirement: Python 3.10+
- Install command: `python -m pip install -r requirements.txt`
- Live command: `python inference.py`
- Output schema: JSON object with artifact kind, count, and predictions
- Data movement: no user data; this fixture is deterministic
- Environment variables: `SENTINEL_FIXTURE_TOKEN` for the simulated live path
- Acceptance ID: `artifact-fixture/v1`
- Model/data version: committed deterministic fixture v1
- Smoke status: self-test passed; live path is simulated
