import unittest
from unittest.mock import Mock

from storage.ks3_client import KS3Client


class KS3ClientTests(unittest.TestCase):
    def setUp(self):
        self.client = KS3Client(
            endpoint="example.invalid",
            bucket="bucket",
            ak="access",
            sk="secret",
            prefix="dataset/v2",
        )

    def test_download_uses_https_prefix_and_auth(self):
        response = Mock(status_code=200, content=b"value")
        self.client.session.get = Mock(return_value=response)
        self.assertEqual(self.client.download("folder/a b.bin"), b"value")
        args, kwargs = self.client.session.get.call_args
        self.assertEqual(
            args[0], "https://bucket.example.invalid/dataset/v2/folder/a%20b.bin"
        )
        self.assertTrue(kwargs["headers"]["Authorization"].startswith("KSS access:"))
        self.assertEqual(kwargs["timeout"], 60.0)

    def test_exists_distinguishes_missing_and_server_error(self):
        self.client.session.head = Mock(return_value=Mock(status_code=404))
        self.assertFalse(self.client.exists("missing"))
        self.client.session.head = Mock(
            return_value=Mock(status_code=500, text="server error")
        )
        with self.assertRaisesRegex(RuntimeError, "KS3 exists failed"):
            self.client.exists("broken")

    def test_list_follows_marker_pagination(self):
        first = Mock(
            status_code=200,
            content=(
                b"<ListBucketResult><IsTruncated>true</IsTruncated>"
                b"<NextMarker>dataset/v2/b</NextMarker>"
                b"<Contents><Key>dataset/v2/a</Key></Contents></ListBucketResult>"
            ),
        )
        second = Mock(
            status_code=200,
            content=(
                b"<ListBucketResult><IsTruncated>false</IsTruncated>"
                b"<Contents><Key>dataset/v2/b</Key></Contents></ListBucketResult>"
            ),
        )
        self.client.session.get = Mock(side_effect=[first, second])
        self.assertEqual(
            self.client.list_prefix(""), ["dataset/v2/a", "dataset/v2/b"]
        )
        self.assertEqual(
            self.client.session.get.call_args_list[1].kwargs["params"]["marker"],
            "dataset/v2/b",
        )


if __name__ == "__main__":
    unittest.main()
