import base64
import hashlib
from cryptography.fernet import Fernet
from django.db import models
from django.conf import settings

def get_fernet():
    """Derive a secure 32-byte key from Django's SECRET_KEY."""
    key = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))

class EncryptedCharField(models.CharField):
    """Custom field to encrypt data at rest securely."""
    def from_db_value(self, value, expression, connection):
        if not value: 
            return value
        try:
            return get_fernet().decrypt(value.encode()).decode()
        except Exception:
            return value

    def get_prep_value(self, value):
        if not value: 
            return value
        return get_fernet().encrypt(str(value).encode()).decode()


class TimeStampedModel(models.Model):
    """An abstract base class model that provides self-updating created and modified fields."""
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class TelegramUser(TimeStampedModel):
    """Stores the Telegram user data and their personal encrypted Gemini API Key."""
    telegram_id = models.BigIntegerField(unique=True, primary_key=True)
    username = models.CharField(max_length=255, null=True, blank=True)
    first_name = models.CharField(max_length=255, null=True, blank=True)
    last_name = models.CharField(max_length=255, null=True, blank=True)
    
    # Custom encrypted field for Bring-Your-Own-Key (BYOK)
    gemini_api_key = EncryptedCharField(max_length=255, null=True, blank=True)
    
    # Default signature reference (can be null)
    default_signature = models.ForeignKey(
        'Signature', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='default_for_user'
    )
    
    # Simple rate limiting/spam tracking fields
    last_message_time = models.DateTimeField(null=True, blank=True)
    is_blocked = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.first_name} ({self.telegram_id})"


class Signature(TimeStampedModel):
    """Stores user-specific signatures. Only accessible by the creator."""
    user = models.ForeignKey(TelegramUser, on_delete=models.CASCADE, related_name='signatures')
    name = models.CharField(max_length=50, help_text="Short name for the inline button")
    content = models.TextField(help_text="The actual signature text with markdown/HTML formatting")

    class Meta:
        # Prevent a user from having two signatures with the exact same name
        unique_together = ('user', 'name')

    def __str__(self):
        return f"{self.user.first_name} - {self.name}"
