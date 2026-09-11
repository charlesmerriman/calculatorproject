"""The generated OpenAPI schema at /schema, and the Swagger UI page over it at /docs."""

from calculatorapi.tests.base import CalculatorTestCase


class ApiDocsTests(CalculatorTestCase):
    """Both routes are public, and the page must still find the schema behind /api."""

    def test_schema_is_public_and_documents_the_api(self):
        res = self.client.get('/schema', {'format': 'json'})
        self.assertEqual(res.status_code, 200)
        schema = res.json()
        self.assertTrue(schema['openapi'].startswith('3.'))
        self.assertEqual(schema['info']['title'], 'Uma Carat Calculator API')
        self.assertIn('/calculator-data', schema['paths'])
        self.assertIn('/auth/{provider}/start', schema['paths'])

    def test_schema_leaves_out_itself_and_the_admin(self):
        paths = self.client.get('/schema', {'format': 'json'}).json()['paths']
        self.assertNotIn('/schema', paths)
        self.assertNotIn('/docs', paths)
        self.assertEqual([p for p in paths if p.startswith('/admin')], [])

    def test_docs_page_fetches_the_schema_by_relative_url(self):
        """Production mounts the API under /api, so an absolute /schema would miss it."""
        res = self.client.get('/docs')
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'url: "schema"')

    def test_docs_page_loads_a_pinned_swagger_ui(self):
        res = self.client.get('/docs')
        self.assertContains(res, 'swagger-ui-dist@5.32.15/swagger-ui-bundle.js')
        self.assertNotContains(res, 'swagger-ui-dist@latest')
