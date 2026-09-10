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
    # Public, rendered as the Timeline tile's hover overlay -- the support-card
    # twin of Uma.purpose; see the note there for the cap and the "" default.
    # Card-level ("Great for front runners"); advice about one particular banner
    # belongs on the SupportsOnSupportBanner.recommendation junction instead.
    purpose = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text=(
            "Shown publicly when a player hovers this card's art on the Timeline, "
            "e.g. \"Great for front runners.\" Leave blank to show nothing. Notes "
            "for other editors go in Admin comments instead."
        ),
    )

    def __str__(self):
        # Many characters have 2-3 support cards sharing the exact same name
        # (different rarities/reprints) - appending game_id keeps admin
        # autocomplete/search results unambiguous.
        return f"{self.name} ({self.game_id})" if self.game_id else self.name
