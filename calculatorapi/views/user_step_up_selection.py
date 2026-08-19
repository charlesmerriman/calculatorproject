from rest_framework import serializers

from calculatorapi.eligibility import build_first_jp_date_maps, is_eligible
from calculatorapi.models import (
    BannerStepUp,
    SELECTION_SLOTS,
    SupportCard,
    Uma,
    UserStepUpSelection,
)


class UserStepUpSelectionSerializer(serializers.ModelSerializer):
    """One of the ten cards a user intends to select at a step-up banner.

    Shaped like UserPlannedPurchaseSerializer: PK-writable relations in, ids
    out. Nothing is nested on read -- the frontend already holds every uma and
    support card via the banner catalogues, so an id is enough to join on and
    nesting would repeat the whole catalogue once per slot.

    CONTEXT THIS SERIALIZER EXPECTS
    -------------------------------
    Both keys are optional, and both exist to keep validation off the per-row
    hot path; see _validate_eligibility for why the second one is load-bearing.

      * `first_jp_dates`  -- (uma_map, support_map) from build_first_jp_date_maps().
        Passed in because /calculator-data writes up to ten rows per step-up and
        rebuilding the maps per row would be an N+1 across the whole catalogue.
      * `stored_pairs`    -- {(banner_step_up_id, "uma"|"support", card_id)} the
        user already had saved BEFORE this request.
    """

    banner_step_up = serializers.PrimaryKeyRelatedField(
        queryset=BannerStepUp.objects.all()
    )
    uma = serializers.PrimaryKeyRelatedField(
        queryset=Uma.objects.all(), required=False, allow_null=True
    )
    support = serializers.PrimaryKeyRelatedField(
        queryset=SupportCard.objects.all(), required=False, allow_null=True
    )

    class Meta:
        model = UserStepUpSelection
        fields = ("id", "user", "banner_step_up", "uma", "support", "slot", "is_target")
        read_only_fields = ("user",)

    def validate_slot(self, value):
        if not 1 <= value <= SELECTION_SLOTS:
            raise serializers.ValidationError(
                f"Slot must be between 1 and {SELECTION_SLOTS}."
            )
        return value

    def validate(self, attrs):
        # Client sends these rows id-less (a selection's content IS its
        # identity), so in practice every row is a create and the instance
        # fallbacks below only matter for the admin and for direct API use.
        instance = self.instance
        step_up = attrs.get("banner_step_up") or getattr(
            instance, "banner_step_up", None
        )
        uma = attrs.get("uma", getattr(instance, "uma", None))
        support = attrs.get("support", getattr(instance, "support", None))

        if uma and support:
            raise serializers.ValidationError(
                "Cannot provide both uma and support."
            )
        if not uma and not support:
            raise serializers.ValidationError(
                "A selection must name either an uma or a support card. "
                "An empty slot is an absent row, not a row with no card."
            )
        if step_up is None:
            return attrs

        # The pool is fixed by the step-up's card_type, so a mismatch is a
        # client bug rather than data drift -- reject it outright.
        if step_up.card_type == "uma" and support:
            raise serializers.ValidationError(
                "A ★3 uma step-up cannot select a support card."
            )
        if step_up.card_type == "support" and uma:
            raise serializers.ValidationError(
                "An SSR support step-up cannot select an uma."
            )

        self._validate_eligibility(step_up, uma, support)
        return attrs

    def _validate_eligibility(self, step_up, uma, support):
        """Reject a pick the campaign's JP cutoff does not actually cover.

        The client filters its picker by the same rule, so this is a backstop
        against a stale client persisting a NEW ineligible pick.

        GRANDFATHERING, AND WHY IT IS NOT self.instance
        -----------------------------------------------
        UserPlannedPurchaseSerializer solves the same problem with
        _pairing_is_unchanged, which asks "is this exactly what is already on
        this ROW". That test cannot work here: the client replaces selections
        wholesale with id-less rows, so self.instance is always None and every
        pick would be re-validated on every save.

        That distinction matters because cutoffs are reference data that
        legitimately moves -- editors keep correcting them as real JP dates
        surface. Re-checking untouched picks would mean an admin narrowing one
        campaign's cutoff 400s the entire PATCH for every user holding an
        affected pick, taking their stats and banners down with it, with no way
        back except deleting the pick they cannot see.

        So the same idea is lifted from "this row" to "this user's stored set":
        a (step-up, card) pair the user already had saved is grandfathered,
        while a pair they are adding now is checked. The UI surfaces stale picks
        as a warning instead, which is the right place for it -- silently
        dropping someone's pick because shared data moved is worse than showing
        a flag.
        """
        cutoff = step_up.anniversary_event.jp_cutoff_date
        if cutoff is None:
            return

        card = uma or support
        kind = "uma" if uma else "support"
        stored_pairs = self.context.get("stored_pairs")
        if stored_pairs is not None and (step_up.id, kind, card.id) in stored_pairs:
            return

        uma_dates, support_dates = self._first_jp_dates()
        dates = uma_dates if uma else support_dates
        if not is_eligible(dates.get(card.id), cutoff):
            raise serializers.ValidationError(
                f"{card.name} was released on JP after this step-up's cutoff "
                f"({cutoff.isoformat()}) and cannot be selected."
            )

    def _first_jp_dates(self):
        maps = self.context.get("first_jp_dates")
        if maps is not None:
            return maps
        # Standalone use (admin, direct API), where nobody prebuilt the maps.
        # /calculator-data always supplies them, so this query is the exception.
        return build_first_jp_date_maps()
