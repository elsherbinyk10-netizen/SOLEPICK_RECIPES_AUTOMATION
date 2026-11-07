import io
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs

import caption_backfill


class CaptionShopifyAuthTests(unittest.TestCase):
    def test_token_exchange_uses_shopify_form_encoded_client_credentials(self):
        response = io.BytesIO(b'{"access_token":"caption-test-token","scope":"write_content"}')
        with patch("urllib.request.urlopen", return_value=response) as mocked:
            token = caption_backfill.get_token(
                "solepick-test.myshopify.com", "client-id-test", "client-secret-test"
            )
        self.assertEqual(token, "caption-test-token")
        request = mocked.call_args.args[0]
        self.assertEqual(request.full_url, "https://solepick-test.myshopify.com/admin/oauth/access_token")
        self.assertEqual(request.get_header("Content-type"), "application/x-www-form-urlencoded")
        fields = parse_qs(request.data.decode("ascii"))
        self.assertEqual(fields["grant_type"], ["client_credentials"])
        self.assertEqual(fields["client_id"], ["client-id-test"])
        self.assertEqual(fields["client_secret"], ["client-secret-test"])

    def test_token_exchange_fails_closed_when_access_token_missing(self):
        response = io.BytesIO(b'{"scope":"write_content"}')
        with patch("urllib.request.urlopen", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "no access_token"):
                caption_backfill.get_token(
                    "solepick-test.myshopify.com", "client-id-test", "client-secret-test"
                )

    def test_blog_discovery_selects_only_the_dedicated_recipes_handle(self):
        payload = {
            "data": {"blogs": {"nodes": [
                {"id": "gid://shopify/Blog/1", "title": "News", "handle": "news"},
                {"id": "gid://shopify/Blog/2", "title": "Recipes", "handle": "recipes"},
            ]}}
        }
        response = io.BytesIO(__import__("json").dumps(payload).encode())
        with patch("urllib.request.urlopen", return_value=response) as mocked:
            blog_id = caption_backfill.resolve_recipe_blog_id(
                "solepick-test.myshopify.com", "caption-test-token", "2026-07"
            )
        self.assertEqual(blog_id, "gid://shopify/Blog/2")
        request = mocked.call_args.args[0]
        self.assertIn("/admin/api/2026-07/graphql.json", request.full_url)
        self.assertEqual(request.get_header("X-shopify-access-token"), "caption-test-token")

    def test_blog_discovery_fails_closed_when_recipes_handle_is_missing(self):
        payload = {"data": {"blogs": {"nodes": [
            {"id": "gid://shopify/Blog/1", "title": "News", "handle": "news"}
        ]}}}
        response = io.BytesIO(__import__("json").dumps(payload).encode())
        with patch("urllib.request.urlopen", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "handle 'recipes' was not found"):
                caption_backfill.resolve_recipe_blog_id(
                    "solepick-test.myshopify.com", "caption-test-token", "2026-07"
                )


if __name__ == "__main__":
    unittest.main()
