"""POST /feedback, the endpoint behind the public feedback form."""

from django.urls import reverse
from rest_framework.authtoken.models import Token

from calculatorapi.models import CustomUser, Feedback, MESSAGE_MAX_LENGTH
from calculatorapi.tests.base import CalculatorTestCase


class FeedbackEndpointTests(CalculatorTestCase):
    """POST /feedback — the public form's write-only endpoint.

    Mirrors VisitBeaconEndpointTests in test_analytics: both are unauthenticated,
    throttled write endpoints, and both deliberately hide whether a filter fired.
    """

    def setUp(self):
        self.url = reverse('submit-feedback')

    def test_guest_submission_is_stored(self):
        res = self.client.post(self.url, {
            'category': 'bug',
            'message': 'The timeline scrolls past the last banner.',
            'source_path': '/app/timeline',
        })
        self.assertEqual(res.status_code, 201)
        entry = Feedback.objects.get()
        self.assertEqual(entry.category, 'bug')
        self.assertEqual(entry.source_path, '/app/timeline')
        # The defining property of a guest submission.
        self.assertIsNone(entry.user)
        self.assertFalse(entry.is_resolved)

    def test_signed_in_submission_is_linked_to_the_account(self):
        user = CustomUser.objects.create_user(
            username='user_a3f9c1', password='x')
        token = Token.objects.create(user=user)
        res = self.client.post(
            self.url,
            {'category': 'feature', 'message': 'Add a dark mode toggle.'},
            HTTP_AUTHORIZATION=f'Token {token.key}',
        )
        self.assertEqual(res.status_code, 201)
        self.assertEqual(Feedback.objects.get().user, user)

    def test_honeypot_returns_success_but_stores_nothing(self):
        """The response must not reveal that the spam filter fired.

        Same contract as the beacon's bot filter: telling the caller it was
        rejected tells whoever is probing which field to stop filling.
        """
        res = self.client.post(self.url, {
            'category': 'other',
            'message': 'buy cheap carats at example.com',
            'website': 'http://example.com',
        })
        self.assertEqual(res.status_code, 201)
        self.assertFalse(Feedback.objects.exists())

    def test_client_cannot_attribute_its_message_to_another_account(self):
        """`user` is not a writable field — the view sets it from the request."""
        victim = CustomUser.objects.create_user(username='victim', password='x')
        res = self.client.post(self.url, {
            'category': 'other',
            'message': 'Not from the victim.',
            'user': victim.pk,
            'is_resolved': True,
        })
        self.assertEqual(res.status_code, 201)
        entry = Feedback.objects.get()
        self.assertIsNone(entry.user)
        self.assertFalse(entry.is_resolved)

    def test_empty_message_is_rejected(self):
        res = self.client.post(self.url, {'category': 'bug', 'message': '   '})
        self.assertEqual(res.status_code, 400)
        self.assertFalse(Feedback.objects.exists())

    def test_over_length_message_is_rejected_cleanly(self):
        res = self.client.post(self.url, {
            'category': 'bug',
            'message': 'x' * (MESSAGE_MAX_LENGTH + 1),
        })
        self.assertEqual(res.status_code, 400)
        self.assertFalse(Feedback.objects.exists())

    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_repeated_submissions_are_eventually_throttled(self):
        # 10/hour, so the 11th is refused. This is the only thing between an
        # open write endpoint and someone filling the table overnight.
        for i in range(10):
            self.client.post(
                self.url, {'category': 'other', 'message': f'report {i}'})
        res = self.client.post(
            self.url, {'category': 'other', 'message': 'one too many'})
        self.assertEqual(res.status_code, 429)

    def test_purging_a_user_keeps_their_feedback(self):
        """SET_NULL, not CASCADE — purge_user_pii must not destroy reports."""
        user = CustomUser.objects.create_user(username='leaving', password='x')
        Feedback.objects.create(
            category='bug', message='Still useful after the account goes.',
            user=user)
        user.delete()
        entry = Feedback.objects.get()
        self.assertIsNone(entry.user)
        self.assertEqual(entry.message, 'Still useful after the account goes.')
