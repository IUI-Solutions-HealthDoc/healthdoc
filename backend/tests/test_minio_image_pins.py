"""CI, development and production must build the same pinned MinIO source."""

import unittest
from pathlib import Path
from unittest.mock import MagicMock

from scripts.init_minio_buckets import provision_private_buckets

ROOT = Path(__file__).resolve().parents[2]
SOURCE_REF = "07c3a429bfed433e49018cb0f78a52145d4bedeb"
IMAGE = "healthdoc-minio-source:2025-09-07"


class MinioImagePinsTest(unittest.TestCase):
    def test_source_revision_is_immutable(self):
        dockerfile = (ROOT / "infra/minio/Dockerfile.source").read_text()
        self.assertIn(f"ARG MINIO_REF={SOURCE_REF}", dockerfile)
        self.assertIn("github.com/minio/minio@${MINIO_REF}", dockerfile)
        self.assertIn("cmd.ReleaseTag=RELEASE.2025-09-07T16-13-09Z", dockerfile)

    def test_ci_development_and_production_use_the_same_build(self):
        for path in (
            ".github/workflows/ci.yml",
            "infra/docker-compose.yml",
            "infra/docker-compose.prod.yml",
        ):
            with self.subTest(path=path):
                content = (ROOT / path).read_text()
                self.assertIn("infra/minio/Dockerfile.source" if path.startswith(".github") else "dockerfile: Dockerfile.source", content)
                self.assertIn(IMAGE, content)
                self.assertNotRegex(content, r"(?:quay\.io|docker\.io)/minio/(?:minio|mc)@")

    def test_initializer_uses_backend_sdk_and_not_unavailable_mc_image(self):
        for path in ("infra/docker-compose.yml", "infra/docker-compose.prod.yml"):
            with self.subTest(path=path):
                content = (ROOT / path).read_text()
                self.assertIn('entrypoint: ["python", "-m", "scripts.init_minio_buckets"]', content)
                self.assertIn("MINIO_ENDPOINT: minio:9000", content)

    def test_initializer_creates_missing_buckets_and_removes_public_policies(self):
        client = MagicMock()
        client.bucket_exists.side_effect = [True, False]
        provision_private_buckets(client, ("existing", "new"))
        client.make_bucket.assert_called_once_with("new")
        self.assertEqual(
            [call.args[0] for call in client.delete_bucket_policy.call_args_list],
            ["existing", "new"],
        )


if __name__ == "__main__":
    unittest.main()
