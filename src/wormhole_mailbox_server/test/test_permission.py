import subprocess
from twisted.trial import unittest
from ..permission import (
    create_permission_provider,
    HashcashPermission,
)


class TestPermission(unittest.TestCase):

    def test_unknown_permission(self):
        with self.assertRaises(ValueError):
            create_permission_provider("unknown-permissions")

    def test_hashcash(self):
        prov = create_permission_provider("hashcash")
        p = prov()
        self.assertIsInstance(p, HashcashPermission)
        data = p.get_welcome_data()
        self.assertFalse(p.verify_permission({"stamp": "asdf"}))

    def test_hashcash_claim_more_bits(self):
        """
        We make a valid hashcash, but _claim_ more bits than the stamp has
        """
        prov = create_permission_provider("hashcash")
        p = prov()
        self.assertIsInstance(p, HashcashPermission)
        data = p.get_welcome_data()

        try:
            stamp = subprocess.check_output([
                "hashcash", "-m", "-C", "-b", str(data["bits"] - 5), "-r", data["resource"]
            ])
        except Exception as e:
            raise unittest.SkipTest("skipping: no hashcash: {}".format(e))

        # we _claim_ X bits, but only have X-5 bits in our hash
        fields = stamp.decode("utf8").split(":")
        fields[1] = str(data["bits"])

        self.assertFalse(
            p.verify_permission({
                "stamp": ":".join(fields),
            })
        )


    def test_no_permission(self):
        prov = create_permission_provider("none")
        p = prov()
        self.assertEqual(
            p.get_welcome_data(),
            {}
        )
        self.assertEqual(
            p.verify_permission({}),
            True
        )
