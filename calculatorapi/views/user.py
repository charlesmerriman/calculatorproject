from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import serializers
from rest_framework.authtoken.models import Token
from django.contrib.auth import authenticate
from calculatorapi.models import CustomUser as User
from calculatorapi.models import ClubRank, TeamTrialsRank, ChampionsMeetingRank


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "password", "first_name", "last_name", "email"]
        extra_kwargs = {"password": {"write_only": True}}


class UserStatsSerializer(serializers.ModelSerializer):

    club_rank = serializers.PrimaryKeyRelatedField(
        required=False, allow_null=True, queryset=ClubRank.objects.all()
    )
    team_trials_rank = serializers.PrimaryKeyRelatedField(
        queryset=TeamTrialsRank.objects.all(),
        required=False,
        allow_null=True,
    )
    champions_meeting_rank = serializers.PrimaryKeyRelatedField(
        queryset=ChampionsMeetingRank.objects.all(),
        required=False,
        allow_null=True,
    )

    class Meta:
        model = User
        fields = [
            "current_carat",
            "uma_ticket",
            "support_ticket",
            "daily_carat",
            "club_rank",
            "team_trials_rank",
            "champions_meeting_rank",
        ]

    def validate_current_carots(self, value):
        if value < 0:
            raise serializers.ValidationError("Current carots cannot be negative.")
        return value


class UserViewSet(viewsets.ViewSet):
    queryset = User.objects.all()
    permission_classes = [permissions.AllowAny]

    @action(detail=False, methods=["post"], url_path="register")
    def register_account(self, request):
        serializer = UserSerializer(data=request.data)
        if serializer.is_valid():
            user = User.objects.create_user(
                username=serializer.validated_data["username"],
                first_name=serializer.validated_data["first_name"],
                last_name=serializer.validated_data["last_name"],
                password=serializer.validated_data["password"],
                email=serializer.validated_data["email"],
            )
            token, created = Token.objects.get_or_create(user=user)
            return Response({"token": token.key}, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=["post"], url_path="login")
    def user_login(self, request):
        username = request.data.get("username")
        password = request.data.get("password")

        user = authenticate(username=username, password=password)

        if user:
            token, created = Token.objects.get_or_create(user=user)
            return Response({"token": token.key}, status=status.HTTP_200_OK)
        else:
            return Response(
                {"error": "Invalid Credentials"}, status=status.HTTP_400_BAD_REQUEST
            )

    @action(
        detail=False,
        methods=["post"],
        url_path="logout",
        permission_classes=[permissions.IsAuthenticated],
    )
    def user_logout(self, request):
        # Delete the user's token
        request.user.auth_token.delete()
        return Response(
            {"message": "Successfully logged out"}, status=status.HTTP_200_OK
        )

    @action(
        detail=False,
        methods=["patch"],
        url_path="update-stats",
        permission_classes=[permissions.IsAuthenticated],
    )
    def update_stats(self, request):
        user = request.user
        serializer = UserStatsSerializer(user, data=request.data, partial=True)

        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
