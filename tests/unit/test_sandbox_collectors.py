import io
import tarfile

import pytest

from backend.app.sandbox.collectors import collect_archive


def archive(name="report.csv", body=b"a,b\n1,2\n", kind=tarfile.REGTYPE):
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w") as tf:
        info = tarfile.TarInfo(name)
        info.type = kind
        info.size = len(body)
        tf.addfile(info, io.BytesIO(body))
    return out.getvalue()


def test_collects_only_allowlisted_regular_file():
    found = collect_archive(archive(), {"report.csv"})
    assert found[0].filename == "report.csv" and found[0].content.startswith(b"a,b")


@pytest.mark.parametrize("name", ["../secret", "/etc/passwd", "out/../secret"])
def test_rejects_traversal_and_absolute_paths(name):
    with pytest.raises(ValueError):
        collect_archive(archive(name), {name})


def test_rejects_unlisted_and_link_outputs():
    with pytest.raises(ValueError, match="allowlist"):
        collect_archive(archive("fake.csv"), {"report.csv"})
    with pytest.raises(ValueError, match="link"):
        collect_archive(archive("report.csv", kind=tarfile.SYMTYPE), {"report.csv"})
