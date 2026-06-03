"""End-to-end walking-skeleton test: CLI -> service -> persistence -> resolve.

Exercises the full vertical slice for the "Shorten a URL" flow:
the CLI shortens a long URL, the service generates a code and persists a
ShortLink, and the same code resolves back to the original URL from storage.
"""

from url_shortener.cli import main
from url_shortener.repository import SqliteLinkRepository


def test_shorten_via_cli_persists_and_resolves(tmp_path, capsys):
    db_path = tmp_path / "links.db"
    long_url = "https://example.com/a/very/long/path?q=1"

    exit_code = main(["shorten", long_url, "--db", str(db_path)])

    assert exit_code == 0
    out = capsys.readouterr().out.strip()
    assert out, "CLI should print the generated short code"

    code = out.split("/")[-1]  # accept either a bare code or a short URL

    # The slice truly persisted: a fresh repository reading the same DB resolves it.
    repo = SqliteLinkRepository(str(db_path))
    assert repo.resolve(code) == long_url
