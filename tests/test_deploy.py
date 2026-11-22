"""The meters of this installation live inline in deploy/nomad.hcl: a typo there only shows after the deploy
(the container exits at startup and Nomad rolls back), so the CI parses it like the agent does."""

import re
import textwrap
from pathlib import Path

from app.config import Settings


def test_nomad_inline_config_loads(tmp_path):
    hcl = Path("deploy/nomad.hcl").read_text(encoding="utf-8")
    body = re.search(
        r'destination = "local/config.yml"\s+data\s+= <<-EOT\n(.*?)\n\s*EOT', hcl, re.S
    ).group(1)
    cfg = tmp_path / "config.yml"
    cfg.write_text(textwrap.dedent(body), encoding="utf-8")
    s = Settings.load({"CONFIG_FILE": str(cfg)})
    assert [m.name for m in s.meters] == ["gas", "wasser"]
    assert all(m.live_url and m.light_on_url and m.light_off_url for m in s.meters)


def test_nomad_job_keeps_the_data_across_allocations():
    hcl = Path("deploy/nomad.hcl").read_text(encoding="utf-8")
    assert re.search(r"ephemeral_disk\s*\{[^}]*sticky\s*=\s*true[^}]*migrate\s*=\s*true", hcl)
    assert 'DATA_DIR         = "/alloc/data"' in hcl
