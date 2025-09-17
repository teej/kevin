from click.testing import CliRunner

from kevin.cli import cli


def test_help_and_version() -> None:
    r = CliRunner().invoke(cli, ["--help"])
    assert r.exit_code == 0
    r = CliRunner().invoke(cli, ["--version"])
    assert r.exit_code == 0
