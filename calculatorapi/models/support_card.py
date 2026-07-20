from django.db import models

class SupportCard(models.Model):
    name = models.CharField(max_length=255)
    game_id = models.PositiveIntegerField(
        unique=True,
        null=True,
        blank=True,
        help_text=(
            "Numeric card id from the reference game data (e.g. 30024). "
            "Anchors this card's image filename in the DO Space."
        ),
    )
    image = models.ImageField(upload_to="support_cards/", blank=True, null=True)
    admin_comments = models.TextField(blank=True, null=True, help_text="Notes for editors.")

    def __str__(self):
        return f"{self.name}"
