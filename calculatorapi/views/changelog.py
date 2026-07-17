from rest_framework.viewsets import ViewSet
from rest_framework.response import Response
from rest_framework import serializers, status, permissions
from calculatorapi.models import ChangelogEntry, ChangelogChange


class ChangelogChangeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChangelogChange
        fields = ("id", "category", "text", "order")


class ChangelogEntrySerializer(serializers.ModelSerializer):
    # Nested changes are read-only here; they're authored via the admin inline.
    # Ordering comes from ChangelogChange.Meta.ordering.
    changes = ChangelogChangeSerializer(many=True, read_only=True)

    class Meta:
        model = ChangelogEntry
        fields = ("id", "title", "version", "date", "changes")


class ChangelogEntryViewSet(ViewSet):
    def get_permissions(self):
        # create/update/destroy are admin-only; list/retrieve serve the public
        # changelog and are open to guests.
        if self.action in ("create", "update", "destroy"):
            return [permissions.IsAdminUser()]
        return [permissions.AllowAny()]

    def list(self, request):
        entries = ChangelogEntry.objects.all().order_by("-date", "-id")
        serializer = ChangelogEntrySerializer(entries, many=True)
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        try:
            entry = ChangelogEntry.objects.get(pk=pk)
        except ChangelogEntry.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        serializer = ChangelogEntrySerializer(entry)
        return Response(serializer.data)

    def create(self, request):
        serializer = ChangelogEntrySerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def update(self, request, pk=None):
        try:
            entry = ChangelogEntry.objects.get(pk=pk)
        except ChangelogEntry.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        serializer = ChangelogEntrySerializer(entry, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def destroy(self, request, pk=None):
        try:
            entry = ChangelogEntry.objects.get(pk=pk)
        except ChangelogEntry.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        entry.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
