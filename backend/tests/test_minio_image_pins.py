"""CI and deployment must use the same immutable official MinIO artifacts."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class MinioImagePinsTest(unittest.TestCase):
    def references(self, path: str, component: str) -> list[str]:
        content = (ROOT / path).read_text()
        # Match actual image references, including an accidentally restored
        # Docker Hub shorthand. Comments describing MinIO are not references.
        return re.findall(
            rf"(?:[\w.-]+/)?minio/{component}(?::[^\s\"']+|@sha256:[a-f0-9]+)",
            content,
        )

    def assert_pinned_and_equal(self, component: str, paths: list[str]) -> None:
        selected = []
        for path in paths:
            refs = self.references(path, component)
            self.assertEqual(len(refs), 1, f"Expected exactly one {component} image in {path}")
            self.assertRegex(refs[0], rf"^quay\.io/minio/{component}@sha256:[a-f0-9]{{64}}$")
            selected.extend(refs)
        self.assertEqual(len(set(selected)), 1, f"{component} image drift: {selected}")

    def test_server_is_identical_in_ci_development_and_production(self):
        self.assert_pinned_and_equal("minio", [
            ".github/workflows/ci.yml", "infra/docker-compose.yml", "infra/docker-compose.prod.yml",
        ])

    def test_initializer_is_identical_in_development_and_production(self):
        self.assert_pinned_and_equal("mc", [
            "infra/docker-compose.yml", "infra/docker-compose.prod.yml",
        ])


if __name__ == "__main__":
    unittest.main()
