from rest_framework import status, permissions
from rest_framework.decorators import api_view, permission_classes
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
        queryset=TeamTrialsRank.objects.all(), required=False, allow_null=True
    )
    champions_meeting_rank = serializers.PrimaryKeyRelatedField(
        queryset=ChampionsMeetingRank.objects.all(), required=False, allow_null=True
    )

    class Meta:
        model = User
        fields = [
            "current_carat", "uma_ticket", "support_ticket",
            "daily_carat", "club_rank", "team_trials_rank", "champions_meeting_rank",
        ]


@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def register_account(request):
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


@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def user_login(request):
    username = request.data.get("username")
    password = request.data.get("password")
    user = authenticate(username=username, password=password)
    if user:
        token, created = Token.objects.get_or_create(user=user)
        return Response({"token": token.key}, status=status.HTTP_200_OK)
    return Response({"error": "Invalid Credentials"}, status=status.HTTP_400_BAD_REQUEST)


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def user_logout(request):
    request.user.auth_token.delete()
    return Response({"message": "Successfully logged out"}, status=status.HTTP_200_OK)
