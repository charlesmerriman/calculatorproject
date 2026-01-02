from django.db import models


class RecommendationTag(models.Model):
    name = models.CharField(max_length=100)

    def __str__(self):
        return str(self.name) if self.name else "Unnamed Tag"
