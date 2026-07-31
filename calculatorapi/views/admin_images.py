"""
JSON feed of the media bucket, consumed by the admin's image-picker modal.

Like views/analytics.py, this view carries no auth logic of its own: it is
wrapped with ``admin.site.admin_view()`` in calculatorproject/urls.py, which
redirects anonymous and non-staff users to the admin login and marks responses
never-cache. All listing logic lives in calculatorapi.image_library.
"""

from django.http import JsonResponse

from calculatorapi.image_library import (
    image_prefixes,
    list_images,
    listing_is_cached,
    normalize_prefix,
)


def admin_image_library(request):
    """
    Return the images in one media folder as JSON.

    ``?prefix=umas/``   which folder to list (required)
    ``?refresh=1``      bypass the cached listing (the modal's Refresh button)

    The prefix is checked against the allow-list derived from the models'
    ``upload_to`` values, so this can never be pointed at an arbitrary path in
    the bucket even by a staff user.
    """
    prefix = normalize_prefix(request.GET.get("prefix"))
    folders = sorted(image_prefixes())

    if prefix not in folders:
        return JsonResponse(
            {"error": "Unknown image folder.", "images": [], "folders": folders},
            status=400,
        )

    images = list_images(prefix, force_refresh=request.GET.get("refresh") == "1")
    return JsonResponse(
        {
            "prefix": prefix,
            "folders": folders,
            "images": images,
            # An empty list is ambiguous to the client: a genuinely empty folder
            # looks identical to a bucket we couldn't reach. The modal uses this
            # flag to say "couldn't load the library" instead of "no images".
            "available": bool(images) or listing_is_cached(prefix),
        }
    )
