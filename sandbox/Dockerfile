FROM python:3.12-slim

# Verification sandbox — runs build/test/lint on the generated project.
# Network-isolated (network_mode: none in docker-compose.yml).
# Resource-limited: 2 CPUs, 2GB RAM, 5-minute timeout.
#
# Sprint 0: trivial echo build/test to prove the container starts and returns
# a structured result. Sprint 1+ will install project deps and run real checks.

WORKDIR /project

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
