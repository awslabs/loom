"""Every resource-creating API must demand a loom:group tag.

Authorization is keyed on loom:group, and check_resource_group_access now
fails closed for an untagged resource — so a resource created without one is
reachable by nobody but a super-admin. Rather than let the API mint resources
that need a super-admin to rescue, creation is refused at the boundary.

Enforced here and not in the models' set_tags(), because internal paths and the
fail-closed tests still need to be able to construct an untagged resource. The
guarantee is "the API cannot create one", not "the type cannot exist" — and
these tests are what make that guarantee true rather than aspirational.
"""
import unittest

from fastapi import HTTPException

from app.routers.utils import require_group_tag


class TestRequireGroupTag(unittest.TestCase):
    def test_none_is_rejected(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            require_group_tag(None, "agent")
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("loom:group", ctx.exception.detail)
        self.assertIn("agent", ctx.exception.detail)

    def test_empty_dict_is_rejected(self) -> None:
        with self.assertRaises(HTTPException):
            require_group_tag({}, "memory")

    def test_other_tags_without_group_are_rejected(self) -> None:
        """A profile that sets everything except loom:group is still unusable."""
        with self.assertRaises(HTTPException):
            require_group_tag({"loom:owner": "someone", "loom:cost.center": "1000"}, "MCP server")

    def test_blank_group_is_rejected(self) -> None:
        """An empty string is absence, not a group — the same fail-open trap as
        an empty IdP mapping table."""
        with self.assertRaises(HTTPException):
            require_group_tag({"loom:group": ""}, "A2A agent")

    def test_group_present_is_returned_unchanged(self) -> None:
        tags = {"loom:group": "demo", "loom:owner": "demo-admin"}
        self.assertEqual(require_group_tag(tags, "agent"), tags)


if __name__ == "__main__":
    unittest.main()
