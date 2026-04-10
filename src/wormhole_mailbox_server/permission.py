import os
import base64
import hashlib
from zope.interface import (
    Interface,
    Attribute,
    implementer,
)


class IPermission(Interface):
    """
    A server-side method of granting permission to a client.
    """
    name = Attribute("name")

    def get_welcome_data():
        """
        return a dict of information to include under the name of this
        Permission granter (under "permission-required" in the Welcome)
        """

    def verify_permission(submit_permission):
        """
        return a bool indicating if the submit_permission data is a valid
        permission (or not)
        """


def create_permission_provider(kind):
    """
    returns a permissions-provider
    """
    if kind == "none":
        return NoPermission
    elif kind == "hashcash":
        return HashcashPermission
    raise ValueError(
        "Unknown permission provider '{}'".format(kind)
    )


@implementer(IPermission)
class NoPermission(object):
    """
    A no-op permission provider used to grant any client access (the
    default).
    """
    name = "none"

    def get_welcome_data(self):
        return {}

    def verify_permission(self, submit_permission):
        return True


@implementer(IPermission)
class HashcashPermission(object):
    """
    A permission provider that generates a random 'resource' string
    and checks a proof-of-work from the client.
    """
    name = "hashcash"

    def __init__(self, bits=20):
        self._bits = bits

    def get_welcome_data(self):
        """
        Generate the data to include under this method's key in the
        `permission-required` value of the welcome message.

        Should be called at most once per connection.
        """
        self._hashcash_resource = base64.b64encode(os.urandom(8)).decode("utf8")
        return {
            "bits": self._bits,
            "resource": self._hashcash_resource,
        }

    def verify_permission(self, perms):
        """
        :returns bool: an indication of whether the provided permissions
            reply from a client is valid
        """
        # XXX THINK do we need this whole method to be constant-time?
        # (basically impossible if it's not even syntactially valid?)
        stamp = perms.get("stamp", "")
        fields = stamp.split(":")
        if len(fields) != 7:
            return False
        vers, claimed_bits, date, resource, ext, rand, counter = fields
        vers = int(vers)
        if vers != 1:
            return False
        if resource != self._hashcash_resource:
            return False

        claimed_bits = int(claimed_bits)
        if claimed_bits < self._bits:
            return False

        h = hashlib.sha1()
        h.update(stamp.encode("utf8"))
        measured_hash = h.digest()
        if leading_zero_bits(measured_hash) < claimed_bits:
            return False
        return True


def leading_zero_bits(bytestring):
    """
    :returns int: the number of leading zeros in the given byte-string
    """
    measured_bits = 0
    for byte in bytestring:
        bit = 1 << 7
        while bit:
            if byte & bit:
                return measured_bits
            else:
                measured_bits += 1
            bit = bit >> 1


