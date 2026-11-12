import uuid
from datetime import datetime
from pydantic import BaseModel, Field, model_validator


class RegisterPlayerRequest(BaseModel):
    email: str = Field(min_length=5, max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    display_name: str = Field(min_length=2, max_length=120)
    institution: str | None = Field(default=None, max_length=160)


class LoginRequest(BaseModel):
    identifier: str | None = Field(default=None, min_length=3, description="Email or username")
    email: str | None = Field(default=None, min_length=3, description="Alias for identifier")
    password: str = Field(min_length=1)

    @model_validator(mode="after")
    def _ensure_identifier(self) -> "LoginRequest":
        if not self.identifier and self.email:
            self.identifier = self.email
        if not self.identifier:
            raise ValueError("Either 'identifier' or 'email' is required.")
        return self


class UserProfileResponse(BaseModel):
    user_id: uuid.UUID
    email: str
    username: str
    role: str
    participant_id: uuid.UUID | None = None
    tournament_code: str | None = None
    display_name: str | None = None
    institution: str | None = None
    created_at: datetime


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserProfileResponse
