from django.db import models
from django.utils import timezone
from datetime import timedelta

# Create your models here.
class Tool(models.Model):
    id = models.AutoField(primary_key=True)  # Auto-increment ID
    name = models.CharField(max_length=255)  # Name des Werkzeugs
    description = models.TextField(blank=True)  # Beschreibung des Werkzeugs, optional
    tagid = models.CharField(max_length=255, blank=True, null=True)  # RFID Tag ID - optional (kein Unique mehr, damit mehrere Tools ohne Tag-ID möglich sind)
    cabinet_number = models.CharField(max_length=50, blank=True, null=True)  # Schranknummer
    category = models.CharField(max_length=100, blank=True, null=True)  # Kategorie

    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = "Werkzeuge"

class User(models.Model):
    name = models.CharField(max_length=255)
    nachname = models.CharField(max_length=255)
    email = models.EmailField(max_length=255, unique=True)
    cardID = models.CharField(primary_key=True)

    class Meta:
        verbose_name_plural = 'user'

def default_return_date():
    # Gibt ein Standard-Rückgabedatum (3 Tage in der Zukunft) zurück
    return timezone.now().date() + timedelta(days=3)

class Loan(models.Model):
    tool = models.OneToOneField(Tool, on_delete=models.CASCADE, primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    note = models.TextField(blank=True)
    borrow_date = models.DateTimeField(default=timezone.now)
    return_date = models.DateField(default=default_return_date)

    class Meta:
        verbose_name_plural = "Ausleihen"

class History(models.Model):
    tagid = models.CharField(max_length=255)
    toolname = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    cardID = models.CharField()
    name = models.CharField(default="name")
    nachname = models.CharField(default="nachname")
    email = models.EmailField(default="email@email.de")
    note = models.TextField(blank=True)
    borrow_date = models.DateTimeField()
    return_date = models.DateField(default=default_return_date())
    returned_date = models.DateTimeField(default=timezone.now)
    returned_by = models.CharField()

    class Meta:
        verbose_name_plural = "Ausleih-Historie"


