FROM python:3.12-slim

# Verification sandbox — runs build/test/lint on the generated project.
# Network-isolated (--network none, applied per run by SandboxRunner; §5).
# Resource-limited: 2 CPUs, 2GB RAM, 5-minute timeout.
#
# The project under test is bind-mounted at /project per run. The image carries
# the deterministic-check toolchain (§4.6) so checks run without network access.

WORKDIR /project

# Verification toolchain — must be baked in: the sandbox runs with --network none,
# so nothing can be pip-installed at verification time.
RUN pip install --no-cache-dir \
    "pytest>=8" \
    "pytest-cov>=5" \
    "ruff>=0.5" \
    "mypy>=1.10"

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Default entrypoint is the Sprint 0 self-contained check script. The Sprint 1+
# SandboxRunner overrides it with `--entrypoint bash -c "<check command>"`.
ENTRYPOINT ["/entrypoint.sh"]
