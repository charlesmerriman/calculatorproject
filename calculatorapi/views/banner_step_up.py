from rest_framework import serializers

from calculatorapi.models import BannerStepUp

from .banner_timeline import BannerTimelineSerializer


class BannerStepUpSerializer(serializers.ModelSerializer):
    """A Select Step-Up banner, shaped like its BannerUma / BannerSupport peers.

    `banner_timeline` is nested exactly as it is on those two, because that is
    what lets the client resolve all three kinds of row through one code path
    (`plannedBannerTarget` / `plannedBannerTimeline`).

    Two derived fields the client would otherwise have to re-derive:

      * `max_steps` — banner_count x 5, the real ceiling on a plan. Sent rather
        than computed client-side so the count and the rule stay together.
      * `jp_cutoff_date` — the campaign's cutoff, folded in the same way
        AnniversaryEventProductSerializer folds it, so a row can show what its
        candidate pool is bounded by without joining the campaign itself.
    """

    banner_timeline = BannerTimelineSerializer()
    max_steps = serializers.IntegerField(read_only=True)
    jp_cutoff_date = serializers.DateField(
        source="anniversary_event.jp_cutoff_date", read_only=True
    )

    class Meta:
        model = BannerStepUp
        fields = (
            "id",
            "banner_timeline",
            "anniversary_event",
            "name",
            "card_type",
            "banner_count",
            "max_steps",
            "jp_cutoff_date",
            "image",
            "admin_comments",
            "order",
        )
