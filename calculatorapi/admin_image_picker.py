"""
"Choose an existing image" support for the admin change forms.

Adds a *Browse library* button next to every image upload field. The button
opens a modal (static/admin/spaces-image-picker.js) that lists what is already
in the media bucket and lets the editor click a thumbnail instead of uploading
a duplicate. Uploading from your computer still works exactly as before — the
two paths sit side by side on the same field, and an upload always wins if both
are used in one submit.

Three pieces, in dependency order:

  SpacesImagePickerWidget  renders the extra button + a hidden key input
  SpacesImagePickerForm    writes a picked key onto the instance on save
  SpacesImagePickerMixin   wires both into a ModelAdmin, zero config

This is admin-layer code (forms, widgets, ModelAdmin), which is why it lives
here next to admin_dashboard.py rather than in the pure-logic image_library.
"""

from django import forms
from django.db import models
from django.urls import reverse
from unfold.widgets import UnfoldAdminImageFieldWidget

from .image_library import invalidate, is_valid_key, normalize_prefix


def library_key_param(html_name):
    """
    Name of the hidden input carrying the picked key for field ``html_name``.

    Mirrors Django's own convention for ClearableFileInput's companion input
    (``image-clear``), so the two can't collide with each other or with a real
    model field.
    """
    return f"{html_name}-library-key"


class SpacesImagePickerWidget(UnfoldAdminImageFieldWidget):
    """
    Unfold's themed file input, plus the library picker controls.

    Subclassing unfold's widget (rather than Django's AdminFileWidget) is what
    keeps the upload control looking like the rest of the themed admin — the
    template re-includes unfold's markup verbatim and only appends to it.
    """

    template_name = "admin/widgets/spaces_image_picker.html"

    def __init__(self, prefix="", attrs=None):
        # Which bucket folder this field's images live in, i.e. its upload_to.
        self.prefix = normalize_prefix(prefix)
        super().__init__(attrs)

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        # `name` here is already prefixed by the form (e.g. "image"), which is
        # exactly what the hidden input must be named for the form to find it.
        context["widget"]["library"] = {
            "prefix": self.prefix,
            "key_input_name": library_key_param(name),
            "endpoint": reverse("admin-image-library"),
        }
        return context

    class Media:
        css = {"all": ("admin/spaces-image-picker.css",)}
        js = ("admin/spaces-image-picker.js",)


class SpacesImagePickerForm(forms.ModelForm):
    """
    ModelForm that applies a library selection to the instance.

    ``picker_fields`` is set per-admin by SpacesImagePickerMixin.get_form().
    An admin needing its own form should subclass this one.
    """

    picker_fields = ()

    def _post_clean(self):
        # _post_clean is where ModelForm copies cleaned_data onto the instance
        # (construct_instance), so it is the earliest point at which we can see
        # the result of a normal upload and the latest at which we can still
        # attach form errors.
        super()._post_clean()
        for field_name in self.picker_fields:
            self._apply_library_choice(field_name)

    def _apply_library_choice(self, field_name):
        html_name = self.add_prefix(field_name)
        key = (self.data.get(library_key_param(html_name)) or "").strip()
        if not key:
            return

        # A file chosen from the editor's computer always wins. super() has
        # already attached that upload to the instance, and re-pointing the
        # field at a library key here would silently discard it.
        if self.files.get(html_name):
            return

        if not is_valid_key(key):
            self.add_error(
                field_name, "That image is not in the media library."
            )
            return

        # The whole trick: assigning the key string points the field at a file
        # that already exists in the Space. Nothing is uploaded or copied.
        setattr(self.instance, field_name, key)


class SpacesImagePickerMixin:  # pylint: disable=too-few-public-methods
    """
    Drop-in for any ModelAdmin whose model has an ImageField.

    Takes no configuration: the image fields and their bucket folders are both
    read off the model, so a newly added ImageField is picked up automatically
    and no fieldsets need editing.
    """

    form = SpacesImagePickerForm

    def _picker_image_fields(self):
        """Names of the ImageFields this picker can handle, in model order."""
        return tuple(
            field.name
            for field in self.model._meta.get_fields()
            # A callable upload_to has no single listable folder, so those keep
            # the plain upload-only widget rather than a picker with no source.
            if isinstance(field, models.ImageField)
            and isinstance(field.upload_to, str)
            and field.upload_to
        )

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if (
            isinstance(db_field, models.ImageField)
            and isinstance(db_field.upload_to, str)
            and db_field.upload_to
        ):
            # setdefault, not assignment: an explicit widget= from a subclass
            # or from formfield_overrides still wins.
            kwargs.setdefault(
                "widget", SpacesImagePickerWidget(prefix=db_field.upload_to)
            )
        return super().formfield_for_dbfield(db_field, request, **kwargs)

    def get_form(self, request, obj=None, change=False, **kwargs):
        # super() builds a fresh class per call via modelform_factory, so
        # setting the attribute here can't leak between admins or requests.
        form_class = super().get_form(request, obj, change=change, **kwargs)
        form_class.picker_fields = self._picker_image_fields()
        return form_class

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        # A new upload changes what every *other* form's picker should offer,
        # so drop that folder's cached listing instead of waiting out the TTL.
        for field_name in self._picker_image_fields():
            if form.files.get(form.add_prefix(field_name)):
                invalidate(obj._meta.get_field(field_name).upload_to)
