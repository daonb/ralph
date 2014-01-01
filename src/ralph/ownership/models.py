from django.db import models as db
from django.utils.translation import ugettext_lazy as _
from lck.django.common.models import TimeTrackable, EditorTrackable

class OwnershipManager(db.Manager):
    ''' This manager holds all the functions that change ownership '''
    def grant(self, device, user, expires_on=None):
        return self.create(user=user, device=device, expires_on=expires_on)

    def assign_to(self, device, user):
        o = self.filter(device=device).latest()
        o.user = user
        o.save()

    def get_owner(self, device):
        try:
            return self.filter(device=device).latest().user
        except Ownership.DoesNotExist:
            return None

    def release(self, device):
        try:
            self.filter(device=device).latest().delete()
        except Ownership.DoesNotExist:
            pass

    def update(self):
        self.filter(expires_on__lte=datetime.now()).delete()

class Ownership(TimeTrackable, EditorTrackable):
    user = db.ForeignKey(
        'auth.User',
        verbose_name=_("profile"),
    )
    device = db.ForeignKey(
        'discovery.Device',
        verbose_name=_("device"),
    )
    expires_on = db.DateTimeField(verbose_name=_("ownership expiration"),
        null=True,
        blank=True,
        default=None,
    )
    objects = OwnershipManager()

    class Meta:
        verbose_name = _("device ownership")
        get_latest_by = "created"
        ordering = ["-created"]

