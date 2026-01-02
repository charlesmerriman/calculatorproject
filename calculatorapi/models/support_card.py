from django.db import models


class SupportCard(models.Model):
    name = models.CharField(max_length=255)
    image = models.ImageField(upload_to="support_cards/", blank=True, null=True)
    admin_comments = models.TextField(blank=True, null=True)
