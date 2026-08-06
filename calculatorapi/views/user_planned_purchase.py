from rest_framework import serializers

from calculatorapi.eligibility import build_first_jp_date_maps, is_eligible
from calculatorapi.models import (
    AnniversaryEventProduct,
    SupportCard,
    Uma,
    UserPlannedPurchase,
)


class UserPlannedPurchaseSerializer(serializers.ModelSerializer):
    """A purchase the user plans to make at a campaign.

    Mirrors UserPlannedBannerSerializer: PK-writable relations on the way in,
    ids on the way out. Unlike planned banners this does NOT nest the product on
    read — the frontend already holds every campaign and its products in
    anniversary_event_data, so an id is enough to join on and nesting would
    duplicate the catalogue once per planned row.
    """

    product = serializers.PrimaryKeyRelatedField(
        queryset=AnniversaryEventProduct.objects.all()
    )
    target_uma = serializers.PrimaryKeyRelatedField(
        queryset=Uma.objects.all(), required=False, allow_null=True
    )
    target_support = serializers.PrimaryKeyRelatedField(
        queryset=SupportCard.objects.all(), required=False, allow_null=True
    )

    class Meta:
        model = UserPlannedPurchase
        fields = (
            "id",
            "user",
            "product",
            "quantity",
            "target_uma",
            "target_support",
        )
        read_only_fields = ("user",)

    def validate(self, attrs):
        # On a PATCH only the changed keys arrive, so fall back to the instance
        # for anything absent -- otherwise partial updates would validate against
        # a half-empty picture and let an ineligible pairing through.
        instance = self.instance
        product = attrs.get("product") or getattr(instance, "product", None)
        target_uma = attrs.get(
            "target_uma", getattr(instance, "target_uma", None)
        )
        target_support = attrs.get(
            "target_support", getattr(instance, "target_support", None)
        )

        if target_uma and target_support:
            raise serializers.ValidationError(
                "Cannot provide both target_uma and target_support."
            )

        if product is None:
            return attrs

        # A carat pack has nothing to select, so a target on one is a client bug
        # rather than a harmless extra field -- reject it rather than silently
        # storing something no reader will ever look at.
        if not product.grants_selector and (target_uma or target_support):
            raise serializers.ValidationError(
                "A carat pack cannot have a selector target."
            )
        if product.product_type == "uma_selector" and target_support:
            raise serializers.ValidationError(
                "A uma selector cannot target a support card."
            )
        if product.product_type == "support_selector" and target_uma:
            raise serializers.ValidationError(
                "A support selector cannot target an uma."
            )

        self._validate_target_eligibility(product, target_uma, target_support)
        return attrs

    def _validate_target_eligibility(self, product, target_uma, target_support):
        """Reject a target the selector's JP cutoff does not actually cover.

        The client filters its picker by the same rule, so this is the backstop
        rather than the primary gate -- but a stale client holding a campaign
        whose cutoff has since been corrected would otherwise persist a plan the
        game will not honour.
        """
        cutoff = product.effective_jp_cutoff_date
        if cutoff is None or not (target_uma or target_support):
            return

        uma_dates, support_dates = build_first_jp_date_maps()
        if target_uma:
            first_jp = uma_dates.get(target_uma.id)
            name = target_uma.name
        else:
            first_jp = support_dates.get(target_support.id)
            name = target_support.name

        if not is_eligible(first_jp, cutoff):
            raise serializers.ValidationError(
                f"{name} was released on JP after this selector's cutoff "
                f"({cutoff.isoformat()}) and cannot be selected."
            )
