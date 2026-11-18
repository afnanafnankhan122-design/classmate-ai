"""Pydantic schemas for student authentication, registration, profile, and password recovery."""

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(..., min_length=2, max_length=150, description="Student's full name")
    email: EmailStr = Field(..., description="Classroom Email (Google account email used for Google Classroom)")
    password: str = Field(..., min_length=8, max_length=128, description="ClassMate AI account password")
    confirm_password: str = Field(..., min_length=8, max_length=128, description="Password confirmation")
    terms_accepted: bool = Field(
        ...,
        description="Affirmative consent to the current Terms of Use and acknowledgment of the Privacy Policy",
    )


class LoginRequest(BaseModel):
    email: EmailStr = Field(..., description="Classroom Email")
    password: str = Field(..., min_length=1, max_length=128, description="ClassMate AI account password")
    remember_me: bool = Field(default=True, description="Persist session")


class ForgotPasswordRequest(BaseModel):
    email: EmailStr = Field(..., description="Registered Classroom Email")


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=32, max_length=128, description="Password reset token")
    new_password: str = Field(..., min_length=8, max_length=128, description="New account password")
    confirm_password: str = Field(..., min_length=8, max_length=128, description="Password confirmation")


class ProfileUpdateRequest(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=150)
    roll_number: str | None = Field(default=None, max_length=100)
    department: str | None = Field(default=None, max_length=150)
    semester: str | None = Field(default=None, max_length=50)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(default="", description="Current account password")
    new_password: str = Field(..., min_length=8, max_length=128, description="New account password")
    confirm_password: str = Field(..., min_length=8, max_length=128, description="Confirm new password")
