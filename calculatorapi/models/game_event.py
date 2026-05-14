from django.db import models

class GameEvent(models.Model):
    name = models.CharField(max_length=255, null=False)
    image = models.ImageField(upload_to="game_events/", null=True, blank=True)
    start_date = models.DateTimeField()
    end_date= models.DateTimeField()

    def __str__(self):
        return str(self.name)
