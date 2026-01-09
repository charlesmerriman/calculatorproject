from django.db import models

class EventReward(models.Model):
    name = models.CharField(max_length=255, null=False)
    carat_amount = models.IntegerField(default=0)
    support_ticket_amount = models.IntegerField(default=0)
    uma_ticket_amount = models.IntegerField(default=0)
    date = models.DateTimeField()

    def __str__(self):
        return str(self.name)
