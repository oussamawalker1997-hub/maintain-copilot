# Contributing

Use Python 3.12+, a virtual environment, and `pip install -e '.[dev]'`. Run Ruff, pytest and the smoke evaluation before proposing a change. Include a regression test when fixing access, lifecycle, numeric applicability, transactional or retrieval behavior.

Describe the concrete problem, resulting behavior and validation. Document architecture decisions when they change a trust boundary or add a dependency. Do not expand the scope by adding agents, models or services without a measured reason.

All committed data must be original synthetic material or explicitly licensed for redistribution. Never commit `.local`, credentials, `.env`, company documents or database files. Evaluation smoke cases are public development fixtures; do not present their pass rate as independent benchmark performance.
